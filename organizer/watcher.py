from __future__ import annotations

import logging
import os
import queue
import signal
import stat
import sys
import threading
import time
from dataclasses import dataclass

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer  # FSEventsObserver on macOS

from . import renamer, tagger
from .config import Config
from .extract import extract
from .llm import LLMError, OllamaUnavailable, Proposal
from .stability import wait_until_stable
from .state import State, file_hash

log = logging.getLogger(__name__)

PARTIAL_EXTS = {".crdownload", ".download", ".part", ".partial", ".tmp", ".opdownload"}
HEARTBEAT_SECONDS = 60
FOLDER_RETRY_SECONDS = 60
STARTUP_POLL_SECONDS = 5
OLLAMA_DOWN_RETRY_SECONDS = 30

FDA_HINT = (
    "macOS denied access to %s. Grant Full Disk Access to the real Python binary "
    "(System Settings > Privacy & Security > Full Disk Access): %s"
)


def ignore_reason(path: str) -> str | None:
    """Cheap name and type checks. Returns why a path is skipped, or None to process it."""
    name = os.path.basename(path)
    if name.startswith("."):
        return "hidden file"
    if os.path.splitext(name)[1].lower() in PARTIAL_EXTS:
        return "partial download"
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISDIR(mode):
        return "directory"
    if not stat.S_ISREG(mode):
        return "not a regular file"
    # Firefox and Chrome keep "name.ext.part" / "name.ext.crdownload" beside a placeholder.
    if any(os.path.lexists(path + ext) for ext in PARTIAL_EXTS):
        return "download still in progress"
    return None


@dataclass
class Result:
    action: str  # renamed | tagged | dry-run | skipped | failed
    original: str
    final_path: str | None = None
    tag: str | None = None
    confidence: float | None = None
    reason: str = ""


class Organizer:
    """The per-file pipeline: stable -> hash -> extract -> model -> rename -> tag -> record."""

    def __init__(self, cfg: Config, state: State, llm, dry_run: bool = False,
                 stop: threading.Event | None = None, stability: dict | None = None):
        self.cfg = cfg
        self.state = state
        self.llm = llm
        self.dry_run = dry_run
        self.stop = stop or threading.Event()
        self.stability = stability or {}

    def process(self, path: str, wait: bool = True, force: bool = False) -> Result:
        """Never raises except OllamaUnavailable, which tells the caller to retry later.
        force handles a file even if its hash was processed before (explicit user request)."""
        path = os.fspath(path)
        original = os.path.basename(path)
        started = time.monotonic()
        try:
            result = self._process(path, original, wait, force)
        except OllamaUnavailable:
            raise
        except FileNotFoundError:
            result = Result("skipped", original, reason="file disappeared during processing")
        except PermissionError as exc:
            result = Result("failed", original, reason=f"permission denied: {exc.filename or path}")
        except LLMError as exc:
            result = Result("failed", original, reason=str(exc))
        except Exception as exc:
            log.exception("unexpected error while processing %r", original)
            result = Result("failed", original, reason=f"{type(exc).__name__}: {exc}")
        self._log(result, time.monotonic() - started)
        return result

    def _log(self, result: Result, seconds: float) -> None:
        new_name = os.path.basename(result.final_path) if result.final_path else None
        confidence = "-" if result.confidence is None else f"{result.confidence:.2f}"
        level = {"failed": logging.ERROR, "skipped": logging.DEBUG}.get(result.action, logging.INFO)
        log.log(
            level, "%s original=%r new=%r tag=%s confidence=%s seconds=%.1f%s",
            result.action, result.original, new_name, result.tag or "-", confidence, seconds,
            f" reason={result.reason}" if result.reason else "",
        )

    def _already_processed(self, path: str) -> str | None:
        digest = file_hash(path)
        return None if not self.state.is_processed(digest) else digest

    def _process(self, path: str, original: str, wait: bool, force: bool = False) -> Result:
        reason = ignore_reason(path)
        if reason:
            return Result("skipped", original, reason=reason)
        # Checked before the stability wait so the service's own renames and tag
        # writes (which fire events) are dismissed without a 6 second poll.
        if not force and self._already_processed(path):
            return Result("skipped", original, reason="already processed")
        if wait and not wait_until_stable(path, stop=self.stop, **self.stability):
            return Result("skipped", original, reason="never became stable, or went away")
        reason = ignore_reason(path)
        if reason:
            return Result("skipped", original, reason=reason)
        st = os.stat(path)
        if st.st_size == 0:
            return Result("skipped", original, reason="empty file")
        digest = file_hash(path)
        if not force and self.state.is_processed(digest):
            return Result("skipped", original, reason="already processed")

        cfg = self.cfg
        stem, ext = renamer.split_ext(original)
        extraction = extract(path, cfg.max_content_bytes)
        if extraction.skip_model:
            proposal = Proposal(stem, cfg.installer_tag, 1.0)
        else:
            proposal = self.llm.propose(extraction, self.stop)

        tag = proposal.tag if proposal.tag in cfg.tags else cfg.fallback_tag
        school = renamer.school_name(proposal.section, proposal.course, proposal.unit_title,
                                     cfg.max_name_length)
        new_stem = school or renamer.sanitize_name(proposal.name, cfg.max_name_length)
        note = ""
        if proposal.confidence < cfg.min_confidence:
            new_stem, note = "", "low confidence, name kept"
        elif not new_stem or new_stem in renamer.GENERIC_NAMES:
            new_stem, note = "", "unusable name from model, name kept"
        else:
            if not extraction.skip_model:
                new_stem = renamer.with_sequence(new_stem, renamer.sequence_label(stem),
                                                 cfg.max_name_length, readable=bool(school))
            if cfg.date_prefix and not school:
                new_stem = renamer.with_date_prefix(new_stem, st.st_mtime, cfg.max_name_length)

        if self.dry_run:
            proposed = f"{new_stem}{ext}" if new_stem else original
            print(f"{original} -> {proposed}  tag={tag}  confidence={proposal.confidence:.2f}"
                  + (f"  ({note})" if note else ""), flush=True)
            return Result("dry-run", original, os.path.join(os.path.dirname(path), proposed),
                          tag, proposal.confidence, note)

        suffix = " ({n})" if school else "-{n}"
        final_path = renamer.rename_in_place(path, new_stem, suffix) if new_stem else path
        renamed = final_path != path
        # Record right after the rename: the hash is what stops reprocessing.
        self.state.record(digest, original, final_path)
        if renamed:
            renamer.log_rename(cfg, path, final_path, tag, digest)
            try:
                renamer.set_original_name(final_path, original)
            except Exception as exc:
                log.warning("could not store original name on %r: %s", os.path.basename(final_path), exc)
        try:
            tagger.add_tag(final_path, tag)
        except Exception as exc:
            note = f"{note}; tagging failed: {exc}".strip("; ")
            log.warning("could not tag %r: %s", os.path.basename(final_path), exc)
        return Result("renamed" if renamed else "tagged", original, final_path, tag, proposal.confidence, note)


class _Handler(FileSystemEventHandler):
    def __init__(self, service: "Service"):
        self.service = service

    def on_created(self, event):
        self.service.enqueue(event.src_path)

    def on_modified(self, event):
        self.service.enqueue(event.src_path)

    def on_moved(self, event):
        self.service.enqueue(event.dest_path)


class Service:
    def __init__(self, cfg: Config, state: State, llm, dry_run: bool = False, stability: dict | None = None):
        self.cfg = cfg
        self.state = state
        self.llm = llm
        self.stop = threading.Event()
        self.organizer = Organizer(cfg, state, llm, dry_run=dry_run, stop=self.stop, stability=stability)
        self.folder = str(cfg.watch_folder)
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._pending: set[str] = set()  # queued or in progress; drops duplicate events
        self._lock = threading.Lock()
        self._observer = None
        self._worker: threading.Thread | None = None

    # -- queue ---------------------------------------------------------------

    def enqueue(self, path) -> bool:
        path = os.fsdecode(path)
        if os.path.dirname(path) != self.folder:  # top level only
            return False
        if ignore_reason(path):
            return False
        with self._lock:
            if path in self._pending:
                return False
            self._pending.add(path)
        self._queue.put(path)
        return True

    def queue_size(self) -> int:
        with self._lock:
            return len(self._pending)

    def _work(self) -> None:
        # Process nothing until the server answers.
        if not self.llm.wait_until_up(self.stop, STARTUP_POLL_SECONDS):
            return
        log.info("Ollama is up at %s, model %s", self.cfg.ollama_host, self.cfg.model)
        while not self.stop.is_set():
            path = self._queue.get()
            if path is None:
                break
            try:
                while not self.stop.is_set():
                    try:
                        self.organizer.process(path)
                        break
                    except OllamaUnavailable:
                        # Keep the file and try again every 30 seconds.
                        log.warning("Ollama is down, keeping %r queued", os.path.basename(path))
                        if self.stop.wait(OLLAMA_DOWN_RETRY_SECONDS):
                            break
                        self.llm.wait_until_up(self.stop, OLLAMA_DOWN_RETRY_SECONDS)
            except Exception:
                log.exception("worker error on %r", path)
            finally:
                with self._lock:
                    self._pending.discard(path)

    # -- lifecycle -----------------------------------------------------------

    def _wait_for_folder(self) -> bool:
        warned = False
        while not self.stop.is_set():
            try:
                os.listdir(self.folder)
                self.state.set_meta("folder_access", "ok")
                return True
            except PermissionError:
                self.state.set_meta("folder_access", "denied")
                if not warned:
                    log.error(FDA_HINT, self.folder, os.path.realpath(sys.executable))
                    warned = True
            except FileNotFoundError:
                if not warned:
                    log.error("watch folder %s does not exist", self.folder)
                    warned = True
            # Stay alive and retry: exiting would make launchd restart us in a loop.
            self.stop.wait(FOLDER_RETRY_SECONDS)
        return False

    def _catch_up(self) -> None:
        last_seen = self.state.last_seen
        if last_seen is None:
            # First run: files already in the folder are left alone.
            self.state.last_seen = time.time()
            log.info("first run: existing files in %s are left untouched", self.folder)
            return
        queued = 0
        with os.scandir(self.folder) as entries:
            for entry in entries:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                # ctime also catches files moved in with an old mtime.
                if max(st.st_mtime, st.st_ctime) > last_seen and self.enqueue(entry.path):
                    queued += 1
        log.info("startup scan: queued %d file(s) changed since last run", queued)

    def _heartbeat(self) -> None:
        now = time.time()
        size = self.queue_size()
        self.state.set_meta("heartbeat", now)
        self.state.set_meta("queue_size", size)
        if size == 0:
            # Only advance while idle so queued files are rescanned after a crash.
            self.state.last_seen = now

    def start(self) -> None:
        """Start the observer and worker threads (used directly by the tests)."""
        self._observer = Observer()
        self._observer.schedule(_Handler(self), self.folder, recursive=False)
        self._observer.start()
        self._worker = threading.Thread(target=self._work, name="worker", daemon=True)
        self._worker.start()

    def shutdown(self) -> None:
        self.stop.set()
        self._queue.put(None)
        if self._observer:
            self._observer.stop()
            self._observer.join(5)
        if self._worker:
            self._worker.join(10)

    def run(self) -> None:
        """Run in the foreground until SIGTERM or SIGINT."""
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: self.stop.set())
        log.info("starting: watching %s%s", self.folder, " (dry run)" if self.organizer.dry_run else "")
        if not self._wait_for_folder():
            return
        self._catch_up()
        self.start()
        self._heartbeat()
        while not self.stop.wait(HEARTBEAT_SECONDS):
            self._heartbeat()
        log.info("stopping")
        self.shutdown()
        self.state.set_meta("queue_size", self.queue_size())
        log.info("stopped")
