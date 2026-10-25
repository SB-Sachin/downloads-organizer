import os

import pytest

from organizer.config import Config
from organizer.llm import Proposal
from organizer.state import State


class FakeLLM:
    """Stands in for the Ollama client. Returns a fixed proposal and records calls."""

    def __init__(self, name="acme-power-electric-bill", tag="finance", confidence=0.9):
        self.proposal = Proposal(name, tag, confidence)
        self.calls = []
        self.error = None

    def propose(self, extraction, stop=None):
        self.calls.append(extraction)
        if self.error:
            raise self.error
        return self.proposal

    def wait_until_up(self, stop, interval=0):
        return True

    def is_up(self):
        return True


@pytest.fixture
def cfg(tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    return Config(watch_folder=watch, state_dir=tmp_path / "state", log_dir=tmp_path / "logs")


@pytest.fixture
def state(cfg):
    state = State(cfg.db_path)
    yield state
    state.close()


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def make_file(cfg):
    def _make(name, content=b"hello world, this is some file content\n"):
        path = os.path.join(cfg.watch_folder, name)
        with open(path, "wb") as fh:
            fh.write(content)
        return path

    return _make
