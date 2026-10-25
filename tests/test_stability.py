import threading
import time

from organizer.stability import wait_until_stable


def test_slow_write_is_not_stable_until_writing_stops(tmp_path):
    path = tmp_path / "download.bin"
    path.write_bytes(b"")
    done_writing = threading.Event()

    def slow_writer():
        with open(path, "ab") as fh:
            for _ in range(15):
                fh.write(b"x" * 1024)
                fh.flush()
                time.sleep(0.04)
        done_writing.set()

    writer = threading.Thread(target=slow_writer)
    writer.start()
    stable = wait_until_stable(path, interval=0.05, required=3, timeout=10)
    finished_first = done_writing.is_set()
    writer.join()
    assert stable
    assert finished_first, "reported stable while the file was still growing"
    assert path.stat().st_size == 15 * 1024


def test_static_file_needs_three_readings(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("done")
    started = time.monotonic()
    assert wait_until_stable(path, interval=0.05, required=3, timeout=5)
    assert time.monotonic() - started >= 0.1  # two waits between three readings


def test_gives_up_after_timeout(tmp_path, caplog):
    path = tmp_path / "forever.bin"
    path.write_bytes(b"")
    stop_writing = threading.Event()

    def endless_writer():
        with open(path, "ab") as fh:
            while not stop_writing.is_set():
                fh.write(b"x")
                fh.flush()
                time.sleep(0.01)

    writer = threading.Thread(target=endless_writer)
    writer.start()
    try:
        assert not wait_until_stable(path, interval=0.03, required=3, timeout=0.4)
    finally:
        stop_writing.set()
        writer.join()
    assert "gave up waiting" in caplog.text


def test_deleted_file_returns_false(tmp_path):
    assert not wait_until_stable(tmp_path / "missing.bin", interval=0.01, timeout=1)


def test_unreadable_file_is_not_stable(tmp_path):
    path = tmp_path / "locked.bin"
    path.write_bytes(b"data")
    path.chmod(0o000)
    try:
        assert not wait_until_stable(path, interval=0.02, required=3, timeout=0.3)
    finally:
        path.chmod(0o644)


def test_stop_event_aborts(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("x")
    stop = threading.Event()
    stop.set()
    assert not wait_until_stable(path, interval=5, required=3, timeout=60, stop=stop)
