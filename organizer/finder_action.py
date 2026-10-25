"""Installs a Finder Quick Action ("Rename with AI") as an Automator service."""
from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .config import PROJECT_ROOT

ACTION_NAME = "Rename with AI"
BUNDLE_ID = "com.user.downloads-organizer.finder-action"
WORKFLOW = Path.home() / "Library" / "Services" / f"{ACTION_NAME}.workflow"


def _command(config_path: str | None) -> str:
    python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)
    config = f" --config {shlex.quote(config_path)}" if config_path else ""
    return (
        'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\n'
        f"cd {shlex.quote(str(PROJECT_ROOT))} || exit 1\n"
        'for f in "$@"; do\n'
        f'    {shlex.quote(str(python))} -m organizer{config} once --force --notify "$f"\n'
        "done\n"
        "exit 0\n"
    )


def _document(command: str) -> dict:
    action = {
        "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
        "AMActionVersion": "2.0.3",
        "AMApplication": ["Automator"],
        "AMParameterProperties": {
            "COMMAND_STRING": {}, "CheckedForUserDefaultShell": {}, "inputMethod": {},
            "shell": {}, "source": {},
        },
        "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
        "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
        "ActionName": "Run Shell Script",
        "ActionParameters": {
            "COMMAND_STRING": command,
            "CheckedForUserDefaultShell": True,
            "inputMethod": 1,  # selected files arrive as arguments
            "shell": "/bin/bash",
            "source": "",
        },
        "BundleIdentifier": "com.apple.RunShellScript",
        "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False,
        "CanShowWhenRun": True,
        "Category": ["AMCategoryUtilities"],
        "Class Name": "RunShellScriptAction",
        "InputUUID": str(uuid.uuid4()).upper(),
        "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
        "OutputUUID": str(uuid.uuid4()).upper(),
        "UUID": str(uuid.uuid4()).upper(),
        "UnlocalizedApplications": ["Automator"],
        "arguments": {},
        "isViewVisible": 1,
    }
    return {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{"action": action, "isViewVisible": 1}],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleID": "com.apple.finder",
            "applicationBundleIDsByPath": {
                "/System/Library/CoreServices/Finder.app": "com.apple.finder",
            },
            "applicationPath": "/System/Library/CoreServices/Finder.app",
            "applicationPaths": ["/System/Library/CoreServices/Finder.app"],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def _info() -> dict:
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": ACTION_NAME,
        "NSServices": [{
            "NSBackgroundColorName": "background",
            "NSIconName": "NSActionTemplate",
            "NSMenuItem": {"default": ACTION_NAME},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": ["public.item"],
        }],
    }


def _is_ours(workflow: Path) -> bool:
    try:
        with open(workflow / "Contents" / "Info.plist", "rb") as fh:
            return plistlib.load(fh).get("CFBundleIdentifier") == BUNDLE_ID
    except (OSError, plistlib.InvalidFileException):
        return False


def _refresh_services() -> None:
    subprocess.run(["/System/Library/CoreServices/pbs", "-update"], capture_output=True, timeout=30)


def install(config_path: str | None = None) -> Path:
    if WORKFLOW.exists() and not _is_ours(WORKFLOW):
        raise FileExistsError(f"{WORKFLOW} exists and was not created by downloads-organizer")
    contents = WORKFLOW / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    with open(contents / "Info.plist", "wb") as fh:
        plistlib.dump(_info(), fh)
    with open(contents / "document.wflow", "wb") as fh:
        plistlib.dump(_document(_command(config_path)), fh)
    _refresh_services()
    return WORKFLOW


def remove() -> bool:
    if not WORKFLOW.exists():
        return False
    if not _is_ours(WORKFLOW):
        raise FileExistsError(f"{WORKFLOW} was not created by downloads-organizer, leaving it")
    shutil.rmtree(WORKFLOW)
    _refresh_services()
    return True


def notify(title: str, message: str) -> None:
    """Best-effort macOS notification."""
    script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
    try:
        subprocess.run(["osascript", "-e", script, title, message], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
