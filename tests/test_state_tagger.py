import plistlib
import subprocess

from organizer import tagger
from organizer.state import State, file_hash


def test_hash_uses_first_megabyte_and_size(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    head = b"h" * (1024 * 1024)
    a.write_bytes(head + b"tail-one")
    b.write_bytes(head + b"tail-two")  # same first MB, same size
    c.write_bytes(head + b"tail-three")  # same first MB, different size
    assert file_hash(a) == file_hash(b)
    assert file_hash(a) != file_hash(c)


def test_state_roundtrip(tmp_path):
    state = State(tmp_path / "sub" / "state.db")
    assert not state.is_processed("abc")
    state.record("abc", "Old Name.pdf", "/x/new-name.pdf")
    assert state.is_processed("abc")
    assert state.last_seen is None
    state.last_seen = 1234.5
    state.close()
    reopened = State(tmp_path / "sub" / "state.db")
    assert reopened.is_processed("abc") and reopened.last_seen == 1234.5
    assert reopened.count() == 1
    reopened.close()


def test_add_tag_with_available_tool(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("x")
    tagger.add_tag(path, "finance")
    tagger.add_tag(path, "finance")
    assert tagger.read_tags(path) == ["finance"]


def test_add_tag_xattr_fallback_writes_binary_plist(tmp_path, monkeypatch):
    monkeypatch.setattr(tagger, "tag_tool", lambda: None)
    path = tmp_path / "file.txt"
    path.write_text("x")
    tagger.add_tag(path, "3d-printing")
    tagger.add_tag(path, "school")  # existing tags are kept
    raw = subprocess.run(["xattr", "-px", tagger.TAGS_XATTR, str(path)], capture_output=True, text=True).stdout
    data = bytes.fromhex(raw)
    assert data.startswith(b"bplist00")
    assert plistlib.loads(data) == ["3d-printing", "school"]
    assert tagger.read_tags(path) == ["3d-printing", "school"]
