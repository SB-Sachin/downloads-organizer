import plistlib

import pytest

from organizer import finder_action


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    path = tmp_path / "Services" / "Rename with AI.workflow"
    monkeypatch.setattr(finder_action, "WORKFLOW", path)
    monkeypatch.setattr(finder_action, "_refresh_services", lambda: None)
    return path


def test_install_writes_a_finder_service(workflow):
    finder_action.install("/tmp/some config.toml")
    info = plistlib.loads((workflow / "Contents" / "Info.plist").read_bytes())
    service = info["NSServices"][0]
    assert service["NSMenuItem"]["default"] == "Rename with AI"
    assert service["NSRequiredContext"]["NSApplicationIdentifier"] == "com.apple.finder"
    document = plistlib.loads((workflow / "Contents" / "document.wflow").read_bytes())
    command = document["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    assert 'once --force --notify "$f"' in command
    assert "--config '/tmp/some config.toml'" in command
    assert document["actions"][0]["action"]["ActionParameters"]["inputMethod"] == 1
    finder_action.install()  # reinstalling over our own bundle is fine
    assert finder_action.remove() is True
    assert not workflow.exists()
    assert finder_action.remove() is False


def test_never_touches_someone_elses_workflow(workflow):
    (workflow / "Contents").mkdir(parents=True)
    (workflow / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "other"}))
    with pytest.raises(FileExistsError):
        finder_action.install()
    with pytest.raises(FileExistsError):
        finder_action.remove()
    assert workflow.exists()
