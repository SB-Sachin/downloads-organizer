from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger(__name__)

POLL_INTERVAL = 2.0
REQUIRED_READINGS = 3
TIMEOUT = 15 * 60


def _opens_for_reading(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            fh.read(1)
        return True
    except FileNotFoundError:
        raise
    except OSError:
        return False


def wait_until_stable(
    path: str | os.PathLike,
    interval: float = POLL_INTERVAL,
    required: int = REQUIRED_READINGS,
    timeout: float = TIMEOUT,
    stop: threading.Event | None = None,
) -> bool:
    """Return True once size and mtime are unchanged for `required` readings in a
    row and the file opens for reading. Return False if the file disappears, the
    stop event fires, or the timeout passes."""
    path = os.fspath(path)
    stop = stop or threading.Event()
    deadline = time.monotonic() + timeout
    last: tuple[int, int] | None = None
    count = 0
    while True:
        try:
            st = os.stat(path)
            reading = (st.st_size, st.st_mtime_ns)
            if reading == last:
                count += 1
            else:
                last, count = reading, 1
            if count >= required and _opens_for_reading(path):
                return True
        except FileNotFoundError:
            return False
        if time.monotonic() >= deadline:
            log.warning("gave up waiting for %r to finish after %.0f s", os.path.basename(path), timeout)
            return False
        if stop.wait(interval):
            return False
