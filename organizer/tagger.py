from __future__ import annotations

import logging
import os
import plistlib
import shutil
import subprocess

log = logging.getLogger(__name__)

TAGS_XATTR = "com.apple.metadata:_kMDItemUserTags"


def tag_tool() -> str | None:
    return shutil.which("tag") or (
        "/opt/homebrew/bin/tag" if os.access("/opt/homebrew/bin/tag", os.X_OK) else None
    )


def read_tags(path: str | os.PathLike) -> list[str]:
    """Finder tag names on a file, read straight from the extended attribute."""
    result = subprocess.run(
        ["xattr", "-px", TAGS_XATTR, os.fspath(path)], capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        return []
    try:
        values = plistlib.loads(bytes.fromhex(result.stdout))
    except Exception:
        return []
    # Finder stores "name\ncolour-index"; keep the name only.
    return [str(value).split("\n")[0] for value in values]


def _add_with_xattr(path: str, tag: str) -> None:
    existing = read_tags(path)
    if tag in existing:
        return
    payload = plistlib.dumps(existing + [tag], fmt=plistlib.FMT_BINARY)
    subprocess.run(
        ["xattr", "-wx", TAGS_XATTR, payload.hex(), path], check=True, capture_output=True, timeout=15
    )


def add_tag(path: str | os.PathLike, tag: str) -> None:
    """Add one Finder tag, keeping any tags already on the file."""
    path = os.fspath(path)
    tool = tag_tool()
    if tool:
        try:
            subprocess.run([tool, "--add", tag, path], check=True, capture_output=True, timeout=15)
            return
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("tag tool failed (%s), falling back to xattr", exc)
    _add_with_xattr(path, tag)
