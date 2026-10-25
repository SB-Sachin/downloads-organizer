"""Calls the real model. Run with: pytest -m slow"""
import re

import pytest
from PIL import Image, ImageDraw

from organizer.config import load_config
from organizer.extract import extract
from organizer.llm import LLM

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def llm():
    cfg = load_config()
    client = LLM(cfg)
    if not client.is_up():
        pytest.skip(f"Ollama is not reachable at {cfg.ollama_host}")
    if not client.model_installed():
        pytest.skip(f"{cfg.model} is not installed")
    return client


def check(proposal, cfg):
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", proposal.name), proposal
    assert len(proposal.name) <= 60
    assert proposal.tag in cfg.tags
    assert 0 <= proposal.confidence <= 1


def test_real_model_names_a_text_file(llm, tmp_path):
    path = tmp_path / "reqs.txt"
    path.write_text(
        "Camping Merit Badge Requirements\n"
        "1. Show that you know first aid for injuries that could occur while camping.\n"
        "2. Learn the Leave No Trace principles and the Outdoor Code.\n"
        "3. Make a written plan for an overnight trek with your patrol.\n"
    )
    proposal = llm.propose(extract(path, llm.cfg.max_content_bytes))
    print(proposal)
    check(proposal, llm.cfg)
    assert "camping" in proposal.name
    assert proposal.tag == "scouts"


def test_real_model_names_an_image(llm, tmp_path):
    path = tmp_path / "IMG_0042.png"
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 860, 460), outline="black", width=4)
    draw.text((80, 90), "INVOICE #1047", fill="black", font_size=64)
    draw.text((80, 200), "Northwind Hardware", fill="black", font_size=48)
    draw.text((80, 290), "Total due: $58.20", fill="black", font_size=48)
    image.save(path)
    proposal = llm.propose(extract(path, llm.cfg.max_content_bytes))
    print(proposal)
    check(proposal, llm.cfg)
    assert any(word in proposal.name for word in ("invoice", "northwind", "hardware"))


def test_real_model_names_class_notes(llm, tmp_path):
    from organizer.renamer import school_name

    path = tmp_path / "IMG_2231 notes.txt"
    path.write_text(
        "Exponential and Logarithmic Functions\n"
        "Pre-Calculus - Ms. Rivera - Period 2\n"
        "3.2 Properties of Logarithms\n"
        "log_b(MN) = log_b M + log_b N\nlog_b(M/N) = log_b M - log_b N\n"
        "1. Expand log_2(8x^3)\n2. Condense 2 log x - log y\n"
    )
    proposal = llm.propose(extract(path, llm.cfg.max_content_bytes))
    print(proposal)
    check(proposal, llm.cfg)
    name = school_name(proposal.section, proposal.course, proposal.unit_title)
    print(name)
    assert name.startswith("3.2 Pre-Calculus - ")
    assert "Logarithm" in name
    assert "Rivera" not in name
    assert proposal.tag == "math"


def test_real_model_leaves_school_fields_empty_for_other_files(llm, tmp_path):
    path = tmp_path / "statement.txt"
    path.write_text("Acme Power\nElectric Bill\nStatement date: September 14, 2026\nAmount due: $132.18\n")
    proposal = llm.propose(extract(path, llm.cfg.max_content_bytes))
    print(proposal)
    assert not proposal.unit_title or not (proposal.section or proposal.course)
