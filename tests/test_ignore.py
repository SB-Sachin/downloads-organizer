import os

import pytest

from organizer.watcher import ignore_reason


@pytest.mark.parametrize("name", [
    "movie.mkv.crdownload", "report.pdf.download", "song.mp3.part", "x.partial",
    "scratch.tmp", "big.iso.opdownload", "UPPER.CRDOWNLOAD",
])
def test_partial_downloads_are_ignored(make_file, name):
    assert ignore_reason(make_file(name)) == "partial download"


@pytest.mark.parametrize("name", [".DS_Store", ".hidden.pdf", ".com.google.Chrome.abc123"])
def test_hidden_files_are_ignored(make_file, name):
    assert ignore_reason(make_file(name)) == "hidden file"


def test_directories_are_ignored(cfg):
    folder = cfg.watch_folder / "some folder"
    folder.mkdir()
    assert ignore_reason(str(folder)) == "directory"


def test_missing_file_is_ignored(cfg):
    assert ignore_reason(str(cfg.watch_folder / "gone.pdf")) == "missing"


def test_symlink_is_ignored(cfg, make_file):
    link = cfg.watch_folder / "link.pdf"
    os.symlink(make_file("real.pdf"), link)
    assert ignore_reason(str(link)) == "not a regular file"


def test_placeholder_beside_partial_is_ignored(make_file):
    # Firefox writes report.pdf (placeholder) next to report.pdf.part while downloading.
    placeholder = make_file("report.pdf")
    make_file("report.pdf.part")
    assert ignore_reason(placeholder) == "download still in progress"


@pytest.mark.parametrize("name", ["report.pdf", "Ünïcödé résumé.docx", "no_extension", "日本語のファイル.txt"])
def test_normal_files_are_accepted(make_file, name):
    assert ignore_reason(make_file(name)) is None
