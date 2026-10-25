import os

import pytest

from organizer import renamer
from organizer.renamer import rename_in_place, sanitize_name, split_ext


@pytest.mark.parametrize("raw,expected", [
    ("acme-power-electric-bill", "acme-power-electric-bill"),
    ("Acme Power  Electric_Bill!!", "acme-power-electric-bill"),
    ("--weird---hyphens--", "weird-hyphens"),
    ("Résumé Déjà Vu", "resume-deja-vu"),
    ("report.final.v2", "report-final-v2"),
    ("日本語", ""),
    ("", ""),
    ("2026-09-14 bill", "2026-09-14-bill"),
])
def test_sanitize_name(raw, expected):
    assert sanitize_name(raw) == expected


def test_sanitize_truncates_at_hyphen_boundary():
    name = "alpha-bravo-charlie-delta-echo-foxtrot-golf-hotel-india-juliet-kilo"
    result = sanitize_name(name, 60)
    assert len(result) <= 60
    assert name.startswith(result + "-")  # ended on a whole word
    assert not result.endswith("-")


def test_sanitize_truncation_exactly_on_boundary():
    assert sanitize_name("abcde-fghij-klmno", 11) == "abcde-fghij"
    assert sanitize_name("abcde-fghij-klmno", 13) == "abcde-fghij"


def test_truncation_keeps_exercise_number_and_drops_partial_title():
    name = "unit-4-right-triangles-and-trigonometry-ex-4-3-special-right-triangles"
    assert sanitize_name(name, 60) == "unit-4-right-triangles-and-trigonometry-ex-4-3"


def test_course_name_that_fits_is_untouched():
    name = "unit-2-quadratic-functions-ex-2-4-completing-the-square"
    assert sanitize_name(name, 60) == name


@pytest.mark.parametrize("raw,expected", [
    ("algebra-2-honors-unit-3-exponents-ex-3-2", "unit-3-algebra-2-honors-exponents-ex-3-2"),
    ("Precalc Unit 4: Trig ex 4.3", "unit-4-precalc-trig-ex-4-3"),
    ("unit-2-quadratics-ex-2-4", "unit-2-quadratics-ex-2-4"),
    ("community-unity-3-notes", "community-unity-3-notes"),
    ("notes-unit-5", "unit-5-notes"),
])
def test_unit_number_goes_first(raw, expected):
    assert sanitize_name(raw) == expected


def test_sanitize_single_long_word_is_hard_cut():
    assert sanitize_name("a" * 100, 60) == "a" * 60


@pytest.mark.parametrize("filename,expected", [
    ("Report.PDF", ("Report", ".pdf")),
    ("backup.tar.gz", ("backup", ".tar.gz")),
    ("noext", ("noext", "")),
    ("a.b.c.TXT", ("a.b.c", ".txt")),
])
def test_split_ext(filename, expected):
    assert split_ext(filename) == expected


def test_rename_keeps_extension_lowercase(make_file):
    new = rename_in_place(make_file("Scan 001.PDF"), "acme-bill")
    assert os.path.basename(new) == "acme-bill.pdf"
    assert os.path.exists(new)


def test_collision_appends_suffix_and_never_overwrites(make_file):
    existing = make_file("acme-bill.pdf", b"first")
    second = rename_in_place(make_file("a.pdf", b"second"), "acme-bill")
    third = rename_in_place(make_file("b.pdf", b"third"), "acme-bill")
    assert os.path.basename(second) == "acme-bill-2.pdf"
    assert os.path.basename(third) == "acme-bill-3.pdf"
    assert open(existing, "rb").read() == b"first"
    assert open(second, "rb").read() == b"second"
    assert open(third, "rb").read() == b"third"


def test_exclusive_rename_refuses_existing_target(make_file):
    src, dst = make_file("src.txt", b"src"), make_file("dst.txt", b"dst")
    with pytest.raises(FileExistsError):
        renamer._rename_exclusive(src, dst)
    assert open(dst, "rb").read() == b"dst"
    assert open(src, "rb").read() == b"src"


def test_rename_to_same_name_is_a_no_op(make_file):
    path = make_file("acme-bill.pdf")
    assert rename_in_place(path, "acme-bill") == path


def test_case_only_rename(make_file, cfg):
    new = rename_in_place(make_file("Acme-Bill.PDF"), "acme-bill")
    assert os.path.basename(new) == "acme-bill.pdf"
    assert sorted(os.listdir(cfg.watch_folder)) == ["acme-bill.pdf"]


def test_original_name_xattr_roundtrip(make_file):
    path = make_file("ünïcode name.txt")
    renamer.set_original_name(path, "Ünïcödé Original (1).txt")
    assert renamer.get_original_name(path) == "Ünïcödé Original (1).txt"
    renamer.set_original_name(path, "later-name.txt")  # first value wins
    assert renamer.get_original_name(path) == "Ünïcödé Original (1).txt"


def test_date_prefix():
    assert renamer.with_date_prefix("acme-bill", 0, 60).endswith("-acme-bill")
    assert renamer.with_date_prefix("2026-09-14-acme-bill", 0, 60) == "2026-09-14-acme-bill"


@pytest.mark.parametrize("section,course,title,expected", [
    ("2.4", "Algebra 2", "Quadratic Functions", "2.4 Algebra 2 - Quadratic Functions"),
    ("Ex 2.4", "Algebra 2", "Quadratic Functions", "2.4 Algebra 2 - Quadratic Functions"),
    ("", "AP Chemistry", "Stoichiometry", "AP Chemistry - Stoichiometry"),
    ("3.1", "", "Limits: An Intro", "3.1 - Limits An Intro"),
    ("3.2", "Pre-Calculus", "Exponential - Log Functions", "3.2 Pre-Calculus - Exponential Log Functions"),
    ("5.1", "", "Chapter 5 Polynomial Functions", "5.1 - Polynomial Functions"),
    ("2.4", "Algebra 2", "Unit 2: Quadratic Functions", "2.4 Algebra 2 - Quadratic Functions"),
    ("2.4", "Algebra 2", "", ""),
    ("", "", "Quadratic Functions", ""),
    ("2.4", "Álgebra 2/Honors", "Funciones Cuadráticas", "2.4 Algebra 2 Honors - Funciones Cuadraticas"),
])
def test_school_name(section, course, title, expected):
    assert renamer.school_name(section, course, title) == expected


def test_school_name_shortens_title_at_a_word():
    name = renamer.school_name("2.4", "Algebra 2", "Quadratic Functions and Their Graphs in Vertex Form", 50)
    assert name == "2.4 Algebra 2 - Quadratic Functions and Their"
    assert len(name) <= 50


def test_school_collision_uses_parenthesised_number(make_file):
    make_file("2.4 Algebra 2 - Quadratic Functions.pdf", b"page one")
    new = rename_in_place(make_file("scan.PDF", b"page two"), "2.4 Algebra 2 - Quadratic Functions", " ({n})")
    assert os.path.basename(new) == "2.4 Algebra 2 - Quadratic Functions (2).pdf"


@pytest.mark.parametrize("original,label", [
    ("page_1", "page1"), ("Page 2", "page2"), ("page-12", "page12"), ("textbook_pg3", "page3"),
    ("p4", "page4"), ("chapter notes part 2", "part2"), ("Slide7", "slide7"),
    ("worksheet q5", "question5"), ("notes_3", "3"), ("bio notes - 2", "2"),
    ("page_1 (1)", "page1"),            # browser copy suffix ignored
    ("statement (4)", ""),              # only a copy suffix
    ("IMG_0042", ""), ("Scan 12", ""), ("DSC_123", ""),
    ("Screenshot 2026-10-02 at 9.41.07 PM", ""),
    ("report2026", ""), ("homework", ""), ("123", ""), ("python3", ""),
])
def test_sequence_label(original, label):
    assert renamer.sequence_label(original) == label


@pytest.mark.parametrize("stem,label,expected", [
    ("math-textbook", "page1", "math-textbook-page1"),
    ("math-textbook-page-1", "page1", "math-textbook-page1"),
    ("math-textbook-page1", "page1", "math-textbook-page1"),
    ("math-textbook-1", "page1", "math-textbook-page1"),
    ("biology-notes", "3", "biology-notes-3"),
    ("biology-notes-3", "3", "biology-notes-3"),
    ("algebra-2-notes", "page2", "algebra-2-notes-page2"),
    ("anything", "", "anything"),
])
def test_with_sequence(stem, label, expected):
    assert renamer.with_sequence(stem, label, 60) == expected


def test_with_sequence_keeps_the_number_when_shortening():
    stem = "alpha-bravo-charlie-delta-echo-foxtrot-golf-hotel-india-juliet"
    result = renamer.with_sequence(stem, "page12", 40)
    assert result.endswith("-page12") and len(result) <= 40


def test_with_sequence_readable():
    assert renamer.with_sequence("2.4 Algebra 2 - Quadratic Functions", "page1", 60, readable=True) \
        == "2.4 Algebra 2 - Quadratic Functions page1"
    assert renamer.with_sequence("2.4 Algebra 2 - Quadratic Functions Page 1", "page1", 60, readable=True) \
        == "2.4 Algebra 2 - Quadratic Functions page1"
    long = renamer.with_sequence("2.4 Algebra 2 - Quadratic Functions and Their Graphs", "page3", 50, readable=True)
    assert long.endswith(" page3") and len(long) <= 50
