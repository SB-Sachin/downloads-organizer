from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

APP_NAME = "downloads-organizer"
LABEL = "com.user.downloads-organizer"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TAGS = [
    "school", "math", "science", "english", "history", "languages", "robotics", "electronics",
    "engineering", "3d-printing", "code", "scouts", "music", "games", "sports", "finance",
    "receipts", "forms", "legal", "health", "travel", "work", "books", "manuals", "screenshots",
    "images", "documents", "archives", "media", "installers", "other",
]


@dataclass
class Config:
    watch_folder: Path = Path("~/Downloads")
    model: str = "gemma3:12b"
    ollama_host: str = "http://localhost:11434"
    keep_alive: int | str = -1
    max_name_length: int = 60
    min_confidence: float = 0.4
    max_content_bytes_gb: float = 2
    date_prefix: bool = False
    tags: list[str] = field(default_factory=lambda: list(DEFAULT_TAGS))
    # Not in the default config.toml, but overridable (the tests point these at a temp dir).
    state_dir: Path = Path(f"~/Library/Application Support/{APP_NAME}")
    log_dir: Path = Path(f"~/Library/Logs/{APP_NAME}")

    def __post_init__(self) -> None:
        # FSEvents reports real paths, so resolve symlinks once here.
        self.watch_folder = Path(os.path.realpath(Path(self.watch_folder).expanduser()))
        self.state_dir = Path(self.state_dir).expanduser()
        self.log_dir = Path(self.log_dir).expanduser()
        self.tags = [str(t).strip() for t in self.tags if str(t).strip()]
        if not self.tags:
            raise ValueError("config: tags must not be empty")

    @property
    def db_path(self) -> Path:
        return self.state_dir / "state.db"

    @property
    def renames_log(self) -> Path:
        return self.state_dir / "renames.jsonl"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "organizer.log"

    @property
    def max_content_bytes(self) -> int:
        return int(self.max_content_bytes_gb * 1024**3)

    @property
    def fallback_tag(self) -> str:
        return "other" if "other" in self.tags else self.tags[-1]

    @property
    def installer_tag(self) -> str:
        return "installers" if "installers" in self.tags else self.fallback_tag


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load config.toml. Lookup order: explicit path, $ORGANIZER_CONFIG, project root."""
    candidate = Path(path or os.environ.get("ORGANIZER_CONFIG") or PROJECT_ROOT / "config.toml")
    if not candidate.exists():
        if path:
            raise FileNotFoundError(f"config file not found: {candidate}")
        return Config()
    with open(candidate, "rb") as fh:
        data = tomllib.load(fh)
    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"{candidate}: unknown setting(s): {', '.join(sorted(unknown))}")
    return Config(**data)
