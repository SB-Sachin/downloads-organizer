from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import subprocess
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from itertools import count

from .config import Config

ORIGINAL_NAME_XATTR = "com.user.original-name"
GENERIC_NAMES = {"document", "file", "image", "untitled"}
COMPOUND_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}(-|$)")
_UNIT = re.compile(r"(?:^|-)(unit-\d+)(?=-|$)")
_COURSE_ID = re.compile(r"(?:^|-)(?:unit|chapter|ch|lesson|section|sec|ex|exercise)-\d+(?:-\d+)*(?=-|$)")

_RENAME_EXCL = 0x4
_libc = ctypes.CDLL(None, use_errno=True)


def split_ext(filename: str) -> tuple[str, str]:
    """Split into (stem, lowercase extension), keeping .tar.gz style pairs together."""
    lower = filename.lower()
    for compound in COMPOUND_EXTS:
        if lower.endswith(compound) and len(filename) > len(compound):
            return filename[: -len(compound)], compound
    stem, ext = os.path.splitext(filename)
    return stem, ext.lower()


def unit_first(slug: str) -> str:
    """Move the first "unit-N" to the front: algebra-2-unit-3-x -> unit-3-algebra-2-x."""
    match = _UNIT.search(slug)
    if not match or match.start(1) == 0:
        return slug
    rest = (slug[: match.start()] + slug[match.end():]).strip("-")
    return f"{match.group(1)}-{rest}" if rest else match.group(1)


def sanitize_name(name: str, max_length: int = 60) -> str:
    """Lowercase ASCII letters and digits in groups joined by single hyphens,
    cut at a hyphen boundary so no word is split. May return an empty string."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = unit_first(re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-"))
    if len(slug) <= max_length:
        return slug
    # Course names end in a title after "ex-2-4"; drop that title whole rather than half of it.
    ends = [m.end() for m in _COURSE_ID.finditer(slug) if m.end() <= max_length]
    if ends and ends[-1] > max_length // 2:
        return slug[: ends[-1]]
    cut = slug[:max_length]
    if slug[max_length] != "-" and "-" in cut:
        cut = cut[: cut.rindex("-")]
    return cut.strip("-")


_SECTION = re.compile(r"\d+(?:\.\d+)*")


def _plain_words(text: str) -> str:
    """Letters, digits, spaces, periods, and in-word hyphens (Pre-Calculus) only."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    kept = re.sub(r"[^A-Za-z0-9.\- ]+", " ", ascii_text)
    kept = re.sub(r"(?<![A-Za-z0-9])-|-(?![A-Za-z0-9])", " ", kept)
    return re.sub(r"\s+", " ", kept).strip(" .")


def school_name(section: str, course: str, unit_title: str, max_length: int = 60) -> str:
    """Class notes read like "2.4 Algebra 2 - Quadratic Functions". Returns "" unless the
    page showed a title plus a section or course."""
    found = _SECTION.search(section or "")
    section = found.group(0) if found else ""
    course = _plain_words(course or "")
    # "Chapter 5 Polynomial Functions" and "Polynomial Functions" are the same unit.
    title = re.sub(r"(?i)^(?:unit|chapter|ch|module)\s*\d+[\s.:-]*", "", _plain_words(unit_title or ""))
    if not title or not (section or course):
        return ""
    head = " ".join(part for part in (section, course) if part)
    name = f"{head} - {title}"
    if len(name) > max_length:
        room = max_length - len(head) - 3
        cut = title[:room]
        if len(title) > room and " " in cut:
            cut = cut[: cut.rindex(" ")]
        name = f"{head} - {cut.strip()}" if cut.strip() else head
    return name


# A number that orders a set of files: page_1, Page 2, part-3, slide4, notes_5.
# Browser copy suffixes like " (1)" and long camera counters like IMG_0042 are not kept.
_COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")
_LABELLED = re.compile(
    r"(?i)(?:^|[^a-z])(page|pg|p|part|pt|slide|sheet|day|week|lesson|problem|question|q|step)"
    r"[\s_.\-#]*(\d{1,4})$"
)
_BARE = re.compile(r"(?i)[a-z][^0-9]*?[\s_\-](\d{1,3})$")
_LABEL_NAMES = {"pg": "page", "p": "page", "pt": "part", "q": "question"}


def sequence_label(original_stem: str) -> str:
    """The ordering number in an original name: "page_1" -> "page1", "notes_3" -> "3"."""
    stem = _COPY_SUFFIX.sub("", original_stem).strip()
    match = _LABELLED.search(stem)
    if match:
        label = match.group(1).lower()
        return f"{_LABEL_NAMES.get(label, label)}{int(match.group(2))}"
    match = _BARE.fullmatch(stem)
    if match and not re.search(r"(?i)(?:^|[^a-z])(img|dsc|scan|screenshot)(?:[^a-z]|$)", stem):
        return str(int(match.group(1)))
    return ""


def with_sequence(stem: str, label: str, max_length: int, readable: bool = False) -> str:
    """Append the ordering label, removing a copy of it the model may already have added."""
    if not label:
        return stem
    number = re.search(r"\d+$", label).group(0)
    word = label[: -len(number)]
    if readable:
        stem = re.sub(rf"(?i)\s*(?:{word or 'page'}\s*)?{number}$", "", stem).rstrip(" -")
        room = max_length - len(label) - 1
        if len(stem) > room:
            cut = stem[:room]
            stem = cut[: cut.rindex(" ")] if " " in cut else cut
        return f"{stem.rstrip(' -')} {label}"
    stem = re.sub(rf"-(?:{word or 'page'}-?)?{number}$", "", stem)
    return f"{sanitize_name(stem, max_length - len(label) - 1)}-{label}".strip("-")


def with_date_prefix(stem: str, mtime: float, max_length: int) -> str:
    if _DATE_PREFIX.match(stem):
        return stem
    date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    return sanitize_name(f"{date}-{stem}", max_length)


def _rename_exclusive(src: str, dst: str) -> None:
    """Rename that fails with FileExistsError instead of replacing dst.
    os.rename alone would silently overwrite, so use renamex_np(RENAME_EXCL)."""
    renamex = getattr(_libc, "renamex_np", None)
    if renamex is not None:
        if renamex(os.fsencode(src), os.fsencode(dst), _RENAME_EXCL) == 0:
            return
        err = ctypes.get_errno()
        if err != errno.ENOTSUP:
            raise OSError(err, os.strerror(err), dst)
    # Filesystem without RENAME_EXCL: check first, then plain rename.
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), dst)
    os.rename(src, dst)


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def rename_in_place(path: str, new_stem: str, suffix: str = "-{n}") -> str:
    """Rename within the same folder, keeping the extension in lowercase.
    Appends -2, -3, ... (or the given suffix) on collision. Returns the final path."""
    folder, filename = os.path.split(path)
    _, ext = split_ext(filename)
    for n in count(1):
        candidate = f"{new_stem}{ext}" if n == 1 else f"{new_stem}{suffix.format(n=n)}{ext}"
        target = os.path.join(folder, candidate)
        if candidate == filename:
            return path
        if os.path.lexists(target):
            if _same_file(path, target):
                # Same file under a case-insensitive spelling (Report.PDF -> report.pdf).
                os.rename(path, target)
                return target
            continue
        try:
            _rename_exclusive(path, target)
            return target
        except FileExistsError:
            continue
    raise AssertionError("unreachable")


def set_original_name(path: str, original_name: str) -> None:
    """Record the first name the file had. A value already present is the true original."""
    probe = subprocess.run(["xattr", "-p", ORIGINAL_NAME_XATTR, path], capture_output=True, timeout=15)
    if probe.returncode == 0:
        return
    subprocess.run(
        ["xattr", "-w", ORIGINAL_NAME_XATTR, original_name, path], check=True, capture_output=True, timeout=15
    )


def get_original_name(path: str) -> str | None:
    probe = subprocess.run(["xattr", "-p", ORIGINAL_NAME_XATTR, path], capture_output=True, text=True, timeout=15)
    return probe.stdout.rstrip("\n") if probe.returncode == 0 else None


def _append(cfg: Config, entry: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with open(cfg.renames_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_rename(cfg: Config, old_path: str, new_path: str, tag: str, digest: str) -> None:
    _append(cfg, {
        "id": uuid.uuid4().hex,
        "action": "rename",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "old_path": old_path,
        "new_path": new_path,
        "tag": tag,
        "hash": digest,
    })


def read_log(cfg: Config) -> list[dict]:
    try:
        with open(cfg.renames_log, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue  # a torn line from a crash mid-write
    return entries


def active_renames(cfg: Config) -> list[dict]:
    """Rename entries that have not been undone, oldest first."""
    entries = read_log(cfg)
    undone = {e.get("undoes") for e in entries if e.get("action") == "undo"}
    return [e for e in entries if e.get("action") == "rename" and e.get("id") not in undone]


@dataclass
class UndoResult:
    ok: bool
    message: str


def _undo_one(cfg: Config, entry: dict) -> UndoResult:
    new_path, old_path = entry["new_path"], entry["old_path"]
    new_name, old_name = os.path.basename(new_path), os.path.basename(old_path)
    if not os.path.lexists(new_path):
        return UndoResult(False, f"{new_name}: no longer there, cannot restore {old_name}")
    try:
        if os.path.lexists(old_path) and _same_file(new_path, old_path):
            os.rename(new_path, old_path)
        else:
            _rename_exclusive(new_path, old_path)
    except FileExistsError:
        return UndoResult(False, f"{new_name}: {old_name} already exists, not overwriting")
    except OSError as exc:
        return UndoResult(False, f"{new_name}: {exc.strerror or exc}")
    subprocess.run(["xattr", "-d", ORIGINAL_NAME_XATTR, old_path], capture_output=True, timeout=15)
    _append(cfg, {
        "action": "undo",
        "undoes": entry["id"],
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "old_path": new_path,
        "new_path": old_path,
    })
    return UndoResult(True, f"{new_name} -> {old_name}")


def undo(cfg: Config, today: bool = False) -> list[UndoResult]:
    """Revert the last rename, or every rename made today (newest first)."""
    candidates = active_renames(cfg)
    if today:
        prefix = time.strftime("%Y-%m-%d")
        candidates = [e for e in candidates if str(e.get("timestamp", "")).startswith(prefix)]
    else:
        candidates = candidates[-1:]
    return [_undo_one(cfg, entry) for entry in reversed(candidates)]
