from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path

HASH_PREFIX_BYTES = 1024 * 1024


def file_hash(path: str | os.PathLike) -> str:
    """SHA-256 of the first 1 MB plus the file size. Cheap for huge files."""
    size = os.stat(path).st_size
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read(HASH_PREFIX_BYTES))
    digest.update(str(size).encode())
    return digest.hexdigest()


class State:
    def __init__(self, db_path: str | os.PathLike):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the worker, the observer thread, and the main thread.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS processed ("
                "hash TEXT PRIMARY KEY, original_name TEXT NOT NULL, "
                "final_path TEXT NOT NULL, timestamp REAL NOT NULL)"
            )
            self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def is_processed(self, digest: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT 1 FROM processed WHERE hash = ?", (digest,)).fetchone()
        return row is not None

    def record(self, digest: str, original_name: str, final_path: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO processed (hash, original_name, final_path, timestamp) VALUES (?, ?, ?, ?)",
                (digest, original_name, final_path, time.time()),
            )

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM processed").fetchone()[0]

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: object) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))

    @property
    def last_seen(self) -> float | None:
        value = self.get_meta("last_seen")
        return float(value) if value is not None else None

    @last_seen.setter
    def last_seen(self, value: float) -> None:
        self.set_meta("last_seen", value)

    def close(self) -> None:
        with self._lock:
            self._db.close()
