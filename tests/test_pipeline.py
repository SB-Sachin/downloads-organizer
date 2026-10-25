import json
import os
import time

from organizer import renamer, tagger
from organizer.llm import LLMError, OllamaUnavailable, Proposal
from organizer.state import file_hash
from organizer.watcher import Organizer, Service

import pytest

FAST = {"interval": 0.02, "required": 3, "timeout": 5}


def organizer(cfg, state, llm, **kwargs):
    return Organizer(cfg, state, llm, stability=FAST, **kwargs)


def test_full_pipeline_renames_tags_and_records(cfg, state, fake_llm, make_file):
    path = make_file("Statement (3).TXT", b"Acme Power electric bill\n")
    digest = file_hash(path)
    result = organizer(cfg, state, fake_llm).process(path)

    assert result.action == "renamed"
    assert os.path.basename(result.final_path) == "acme-power-electric-bill.txt"
    assert os.listdir(cfg.watch_folder) == ["acme-power-electric-bill.txt"]  # stayed in the folder
    assert open(result.final_path, "rb").read() == b"Acme Power electric bill\n"
    assert tagger.read_tags(result.final_path) == ["finance"]
    assert renamer.get_original_name(result.final_path) == "Statement (3).TXT"
    assert state.is_processed(digest)

    entry = json.loads(cfg.renames_log.read_text().strip())
    assert entry["old_path"] == path and entry["new_path"] == result.final_path
    assert entry["tag"] == "finance" and entry["hash"] == digest and entry["timestamp"]
    assert "Original filename: Statement (3).TXT" in fake_llm.calls[0].header


def test_already_processed_hash_is_skipped(cfg, state, fake_llm, make_file):
    org = organizer(cfg, state, fake_llm)
    first = org.process(make_file("a.txt", b"same content"))
    again = org.process(first.final_path)  # the service's own rename event
    duplicate = org.process(make_file("copy.txt", b"same content"))
    assert again.action == duplicate.action == "skipped"
    assert len(fake_llm.calls) == 1
    assert os.path.exists(os.path.join(cfg.watch_folder, "copy.txt"))


def test_low_confidence_keeps_name_and_tags_only(cfg, state, fake_llm, make_file):
    fake_llm.proposal = Proposal("some-guess-name", "school", 0.2)
    path = make_file("homework.txt")
    result = organizer(cfg, state, fake_llm).process(path)
    assert result.action == "tagged" and result.final_path == path
    assert tagger.read_tags(path) == ["school"]
    assert not cfg.renames_log.exists()


@pytest.mark.parametrize("bad_name", ["document", "!!!", ""])
def test_generic_or_empty_name_keeps_original(cfg, state, fake_llm, make_file, bad_name):
    fake_llm.proposal = Proposal(bad_name, "documents", 0.9)
    path = make_file("keep me.txt")
    result = organizer(cfg, state, fake_llm).process(path)
    assert result.action == "tagged" and os.path.exists(path)


def test_tag_outside_list_becomes_other(cfg, state, fake_llm, make_file):
    fake_llm.proposal = Proposal("some-specific-name", "made-up-tag", 0.9)
    result = organizer(cfg, state, fake_llm).process(make_file("a.txt"))
    assert result.tag == "other"


def test_installer_makes_no_model_call(cfg, state, fake_llm, make_file):
    result = organizer(cfg, state, fake_llm).process(make_file("Docker Desktop (1).DMG", b"\x00" * 128))
    assert fake_llm.calls == []
    assert os.path.basename(result.final_path) == "docker-desktop-1.dmg"
    assert tagger.read_tags(result.final_path) == ["installers"]


def test_partial_download_is_never_touched(cfg, state, fake_llm, make_file):
    path = make_file("movie.mkv.crdownload", b"partial bytes")
    result = organizer(cfg, state, fake_llm).process(path)
    assert result.action == "skipped" and fake_llm.calls == []
    assert os.listdir(cfg.watch_folder) == ["movie.mkv.crdownload"]
    assert tagger.read_tags(path) == []


def test_collision_in_pipeline(cfg, state, fake_llm, make_file):
    existing = make_file("acme-power-electric-bill.txt", b"already here")
    state.record(file_hash(existing), "x", existing)
    result = organizer(cfg, state, fake_llm).process(make_file("new.txt", b"new bill"))
    assert os.path.basename(result.final_path) == "acme-power-electric-bill-2.txt"
    assert open(existing, "rb").read() == b"already here"


def test_dry_run_changes_nothing(cfg, state, fake_llm, make_file, capsys):
    path = make_file("Statement.txt")
    result = organizer(cfg, state, fake_llm, dry_run=True).process(path)
    assert result.action == "dry-run"
    assert "Statement.txt -> acme-power-electric-bill.txt  tag=finance" in capsys.readouterr().out
    assert os.listdir(cfg.watch_folder) == ["Statement.txt"]
    assert tagger.read_tags(path) == [] and state.count() == 0


def test_date_prefix(cfg, state, fake_llm, make_file):
    cfg.date_prefix = True
    path = make_file("a.txt")
    os.utime(path, (1789000000, 1789000000))
    result = organizer(cfg, state, fake_llm).process(path)
    expected = time.strftime("%Y-%m-%d", time.localtime(1789000000))
    assert os.path.basename(result.final_path) == f"{expected}-acme-power-electric-bill.txt"


def test_model_failure_leaves_file_alone_and_service_continues(cfg, state, fake_llm, make_file):
    org = organizer(cfg, state, fake_llm)
    fake_llm.error = LLMError("boom")
    bad = make_file("bad.txt", b"one")
    assert org.process(bad).action == "failed"
    assert os.path.exists(bad) and state.count() == 0
    fake_llm.error = RuntimeError("unexpected")
    assert org.process(bad).action == "failed"
    fake_llm.error = None
    assert org.process(make_file("good.txt", b"two")).action == "renamed"


def test_file_deleted_during_processing(cfg, state, fake_llm, make_file):
    path = make_file("vanishing.txt")

    def delete_then_answer(extraction, stop=None):
        os.unlink(path)  # the user deletes the file while the model is thinking
        return Proposal("some-new-name", "other", 0.9)

    fake_llm.propose = delete_then_answer
    result = organizer(cfg, state, fake_llm).process(path)
    assert result.action == "skipped" and "disappeared" in result.reason


def test_empty_file_is_skipped(cfg, state, fake_llm, make_file):
    assert organizer(cfg, state, fake_llm).process(make_file("placeholder.pdf", b"")).reason == "empty file"


def test_unicode_filename(cfg, state, fake_llm, make_file):
    result = organizer(cfg, state, fake_llm).process(make_file("Résumé — 日本語 ✓.txt"))
    assert result.action == "renamed"
    assert renamer.get_original_name(result.final_path) == "Résumé — 日本語 ✓.txt"


def test_ollama_down_propagates_for_requeue(cfg, state, fake_llm, make_file):
    fake_llm.error = OllamaUnavailable("refused")
    path = make_file("wait.txt")
    with pytest.raises(OllamaUnavailable):
        organizer(cfg, state, fake_llm).process(path)
    assert os.path.exists(path) and state.count() == 0


def test_force_reprocesses_a_known_file(cfg, state, fake_llm, make_file):
    org = organizer(cfg, state, fake_llm)
    first = org.process(make_file("a.txt", b"content"))
    assert org.process(first.final_path).action == "skipped"
    fake_llm.proposal = Proposal("a-better-specific-name", "school", 0.9)
    again = org.process(first.final_path, wait=False, force=True)
    assert again.action == "renamed"
    assert os.path.basename(again.final_path) == "a-better-specific-name.txt"
    assert renamer.get_original_name(again.final_path) == "a.txt"  # the first name is kept
    assert len(renamer.undo(cfg, today=True)) == 2
    assert os.listdir(cfg.watch_folder) == ["a.txt"]


def test_class_notes_get_readable_name(cfg, state, fake_llm, make_file):
    fake_llm.proposal = Proposal("algebra-2-quadratics", "math", 0.9, "2.4", "Algebra 2", "Quadratic Functions")
    result = organizer(cfg, state, fake_llm).process(make_file("Scan 12.PDF", b"notes"))
    assert os.path.basename(result.final_path) == "2.4 Algebra 2 - Quadratic Functions.pdf"
    assert tagger.read_tags(result.final_path) == ["math"]
    assert renamer.undo(cfg)[0].ok
    assert os.listdir(cfg.watch_folder) == ["Scan 12.PDF"]


def test_school_fields_without_title_use_normal_name(cfg, state, fake_llm, make_file):
    fake_llm.proposal = Proposal("algebra-2-practice", "math", 0.9, "2.4", "Algebra 2", "")
    result = organizer(cfg, state, fake_llm).process(make_file("a.txt"))
    assert os.path.basename(result.final_path) == "algebra-2-practice.txt"


def test_page_numbers_carry_over(cfg, state, fake_llm, make_file):
    fake_llm.proposal = Proposal("math-textbook", "math", 0.9)
    org = organizer(cfg, state, fake_llm)
    names = [os.path.basename(org.process(make_file(f"page_{n}.png", f"p{n}".encode())).final_path)
             for n in (1, 2, 10)]
    assert names == ["math-textbook-page1.png", "math-textbook-page2.png", "math-textbook-page10.png"]


def test_page_numbers_carry_over_for_class_notes(cfg, state, fake_llm, make_file):
    fake_llm.proposal = Proposal("x", "math", 0.9, "2.4", "Algebra 2", "Quadratic Functions")
    result = organizer(cfg, state, fake_llm).process(make_file("page_2.jpg", b"notes"))
    assert os.path.basename(result.final_path) == "2.4 Algebra 2 - Quadratic Functions page2.jpg"


def test_installer_names_are_not_doubled(cfg, state, fake_llm, make_file):
    result = organizer(cfg, state, fake_llm).process(make_file("tool part 2.dmg", b"\x00" * 64))
    assert os.path.basename(result.final_path) == "tool-part-2.dmg"


# -- undo ---------------------------------------------------------------------

def test_undo_restores_original_name(cfg, state, fake_llm, make_file):
    path = make_file("Original Name.txt")
    result = organizer(cfg, state, fake_llm).process(path)
    outcome = renamer.undo(cfg)
    assert [r.ok for r in outcome] == [True]
    assert os.listdir(cfg.watch_folder) == ["Original Name.txt"]
    assert renamer.get_original_name(path) is None
    assert renamer.undo(cfg) == []  # nothing left
    # The restored file is not renamed again by the service.
    assert organizer(cfg, state, fake_llm).process(path).action == "skipped"
    assert not os.path.exists(result.final_path)


def test_undo_today_reverts_all_newest_first(cfg, state, fake_llm, make_file):
    org = organizer(cfg, state, fake_llm)
    for name in ("one.txt", "two.txt", "three.txt"):
        org.process(make_file(name, name.encode()))
    outcome = renamer.undo(cfg, today=True)
    assert len(outcome) == 3 and all(r.ok for r in outcome)
    assert sorted(os.listdir(cfg.watch_folder)) == ["one.txt", "three.txt", "two.txt"]


def test_undo_never_overwrites(cfg, state, fake_llm, make_file):
    path = make_file("report.txt", b"original")
    result = organizer(cfg, state, fake_llm).process(path)
    make_file("report.txt", b"a newer file took the old name")
    outcome = renamer.undo(cfg)
    assert not outcome[0].ok and "not overwriting" in outcome[0].message
    assert open(path, "rb").read() == b"a newer file took the old name"
    assert open(result.final_path, "rb").read() == b"original"


# -- watcher ------------------------------------------------------------------

def wait_for(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_queue_drops_duplicates_and_ignored_paths(cfg, state, fake_llm, make_file):
    service = Service(cfg, state, fake_llm, stability=FAST)
    path = make_file("a.txt")
    assert service.enqueue(path) is True
    assert service.enqueue(path) is False
    assert service.enqueue(make_file("b.pdf.crdownload")) is False
    assert service.enqueue(make_file(".hidden")) is False
    sub = cfg.watch_folder / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("x")
    assert service.enqueue(str(sub / "nested.txt")) is False  # top level only
    assert service.queue_size() == 1


def test_watcher_end_to_end(cfg, state, fake_llm):
    service = Service(cfg, state, fake_llm, stability=FAST)
    service.start()
    try:
        time.sleep(0.5)  # let FSEvents start streaming
        partial = cfg.watch_folder / "bill.pdf.crdownload"
        partial.write_bytes(b"%PDF-1.4 partial")
        time.sleep(1.0)
        assert os.listdir(cfg.watch_folder) == ["bill.pdf.crdownload"]
        # The browser finishes: the partial file is renamed to its final name.
        partial.write_bytes(b"%PDF-1.4 complete file body")
        os.rename(partial, cfg.watch_folder / "bill.txt")
        target = cfg.watch_folder / "acme-power-electric-bill.txt"
        assert wait_for(target.exists), os.listdir(cfg.watch_folder)
        assert wait_for(lambda: tagger.read_tags(target) == ["finance"])
        assert wait_for(lambda: service.queue_size() == 0)
        time.sleep(1.0)  # own rename/tag events must not cause a second pass
        assert os.listdir(cfg.watch_folder) == ["acme-power-electric-bill.txt"]
        assert len(fake_llm.calls) == 1
    finally:
        service.shutdown()


def test_startup_scan_queues_only_new_unprocessed_files(cfg, state, fake_llm, make_file):
    make_file("old.txt", b"old")
    service = Service(cfg, state, fake_llm, stability=FAST)
    service._catch_up()  # first run: existing files are left alone, last_seen is set
    assert service.queue_size() == 0 and state.last_seen is not None
    time.sleep(0.05)
    state.last_seen = time.time()
    time.sleep(0.05)
    new = make_file("new.txt", b"new")
    make_file("new.pdf.part", b"partial")
    service._catch_up()
    assert service._pending == {new}
