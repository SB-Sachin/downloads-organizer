from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

from . import finder_action, renamer, tagger
from .config import LABEL, Config, load_config
from .state import State


def setup_logging(cfg: Config, verbose: bool = False) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler = RotatingFileHandler(cfg.log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    # Under launchd stderr is a file, so only echo to an interactive terminal.
    if sys.stderr.isatty():
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    for noisy in ("httpx", "httpcore", "fsevents", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _llm(cfg: Config):
    from .llm import LLM

    return LLM(cfg)


def cmd_run(cfg: Config, args) -> int:
    from .watcher import Service

    setup_logging(cfg, args.verbose)
    state = State(cfg.db_path)
    try:
        Service(cfg, state, _llm(cfg), dry_run=args.dry_run).run()
    finally:
        state.close()
    return 0


def cmd_once(cfg: Config, args) -> int:
    from .llm import OllamaUnavailable
    from .watcher import Organizer

    setup_logging(cfg, args.verbose)
    path = os.path.realpath(os.path.expanduser(args.path))
    state = State(cfg.db_path)
    try:
        result = Organizer(cfg, state, _llm(cfg), dry_run=args.dry_run).process(
            path, wait=False, force=args.force)
    except OllamaUnavailable as exc:
        print(f"Ollama is not reachable at {cfg.ollama_host}: {exc}", file=sys.stderr)
        if args.notify:
            finder_action.notify("Rename with AI", "Ollama is not running, nothing was renamed.")
        return 1
    finally:
        state.close()
    if result.action == "renamed":
        message = (f"{result.original} -> {os.path.basename(result.final_path)}  tag={result.tag}  "
                   f"confidence={result.confidence:.2f}")
    elif result.action == "tagged":
        message = (f"{result.original}: name kept, tag={result.tag}  confidence={result.confidence:.2f}"
                   + (f"  ({result.reason})" if result.reason else ""))
    elif result.action == "dry-run":
        return 0  # the proposal was already printed
    else:
        message = f"{result.original}: {result.action} ({result.reason})"
    print(message)
    if args.notify:
        finder_action.notify("Rename with AI", message)
    return 1 if result.action == "failed" else 0


def cmd_finder_action(cfg: Config, args) -> int:
    try:
        if args.operation == "install":
            config = os.path.abspath(args.config) if args.config else None
            print(f"installed: {finder_action.install(config)}")
            print(f'In Finder: right-click a file > Quick Actions > "{finder_action.ACTION_NAME}"')
        else:
            removed = finder_action.remove()
            print("removed the Finder Quick Action" if removed else "the Finder Quick Action was not installed")
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_undo(cfg: Config, args) -> int:
    results = renamer.undo(cfg, today=args.today)
    if not results:
        print("Nothing to undo." if not args.today else "No renames from today to undo.")
        return 0
    for result in results:
        print(("restored: " if result.ok else "FAILED:   ") + result.message)
    return 0 if all(r.ok for r in results) else 1


def _service_state() -> str:
    target = f"gui/{os.getuid()}/{LABEL}"
    result = subprocess.run(["launchctl", "print", target], capture_output=True, text=True)
    if result.returncode != 0:
        return "not loaded in launchd"
    fields = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if sep and key in ("state", "pid") and key not in fields:
            fields[key] = value
    return f"{fields.get('state', 'unknown')}" + (f" (pid {fields['pid']})" if "pid" in fields else "")


def cmd_status(cfg: Config, args) -> int:
    print(f"Service:      {_service_state()}")
    if cfg.db_path.exists():
        state = State(cfg.db_path)
        heartbeat = state.get_meta("heartbeat")
        age = f"{time.time() - float(heartbeat):.0f} s ago" if heartbeat else "never"
        print(f"Heartbeat:    {age}")
        print(f"Queue size:   {state.get_meta('queue_size') or 0}")
        print(f"Processed:    {state.count()} file(s)")
        state.close()
    else:
        print("Queue size:   0 (the service has not run yet)")
    llm = _llm(cfg)
    if not llm.is_up():
        print(f"Model:        Ollama not reachable at {cfg.ollama_host}")
    elif not llm.model_installed():
        print(f"Model:        {cfg.model} is not installed (run: ollama pull {cfg.model})")
    else:
        loaded = cfg.model in llm.loaded_models()
        print(f"Model:        {cfg.model} installed, {'loaded in memory' if loaded else 'not loaded yet'}")
    renames = renamer.active_renames(cfg)[-10:]
    print(f"Last {len(renames)} rename(s):" if renames else "No renames yet.")
    for entry in renames:
        print(f"  {entry['timestamp']}  {os.path.basename(entry['old_path'])} -> "
              f"{os.path.basename(entry['new_path'])}  [{entry['tag']}]")
    return 0


def cmd_doctor(cfg: Config, args) -> int:
    failures = 0

    def report(ok: bool, label: str, detail: str = "", warn_only: bool = False) -> None:
        nonlocal failures
        if not ok and not warn_only:
            failures += 1
        mark = "ok  " if ok else ("warn" if warn_only else "FAIL")
        print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))

    real_python = os.path.realpath(sys.executable)
    llm = _llm(cfg)
    up = llm.is_up()
    report(up, "Ollama reachable", cfg.ollama_host if up else f"no answer from {cfg.ollama_host}")
    if up:
        installed = llm.model_installed()
        report(installed, f"model {cfg.model} installed", "" if installed else f"run: ollama pull {cfg.model}")
    tool = tagger.tag_tool()
    report(bool(tool), "tag tool", tool or "missing, xattr fallback will be used (brew install tag)",
           warn_only=True)
    try:
        os.listdir(cfg.watch_folder)
        report(True, "watch folder readable", str(cfg.watch_folder))
    except PermissionError:
        report(False, "watch folder readable",
               f"Full Disk Access is missing. Add this binary in System Settings > "
               f"Privacy & Security > Full Disk Access: {real_python}")
    except FileNotFoundError:
        report(False, "watch folder readable", f"{cfg.watch_folder} does not exist")
    # The check above runs with this terminal's permissions; launchd's can differ.
    if cfg.db_path.exists():
        state = State(cfg.db_path)
        access = state.get_meta("folder_access")
        state.close()
        if access == "denied":
            report(False, "background service folder access",
                   f"the launchd service was denied. Grant Full Disk Access to {real_python}")
        elif access == "ok":
            report(True, "background service folder access", "last start could read the folder")
    print(f"       python binary for Full Disk Access: {real_python}")
    print(f"       service: {_service_state()}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m organizer", description="Rename and tag finished downloads.")
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--verbose", action="store_true", help="also log skipped files")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start the watcher in the foreground")
    run.add_argument("--dry-run", action="store_true", help="print proposals, rename nothing")
    once = sub.add_parser("once", help="process one file")
    once.add_argument("path")
    once.add_argument("--dry-run", action="store_true")
    once.add_argument("--force", action="store_true", help="handle the file even if it was processed before")
    once.add_argument("--notify", action="store_true", help="show the result as a macOS notification")
    finder = sub.add_parser("finder-action", help='add or remove the Finder "Rename with AI" Quick Action')
    finder.add_argument("operation", choices=["install", "remove"])
    undo = sub.add_parser("undo", help="revert the last rename")
    undo.add_argument("--today", action="store_true", help="revert every rename made today")
    sub.add_parser("status", help="queue size, model state, last 10 renames")
    sub.add_parser("doctor", help="check the setup")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    handler = {"run": cmd_run, "once": cmd_once, "undo": cmd_undo, "status": cmd_status, "doctor": cmd_doctor,
               "finder-action": cmd_finder_action}
    return handler[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
