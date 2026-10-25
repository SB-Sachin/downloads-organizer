import json

import httpx
import pytest

from organizer.extract import Extraction
from organizer.llm import LLM, SYSTEM_PROMPT, LLMError, OllamaUnavailable


class StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"message": {"content": response}}


@pytest.fixture
def llm(cfg):
    return LLM(cfg, backoff=0.01)


GOOD = json.dumps({"name": "acme-bill", "tag": "finance", "confidence": 0.8})


def test_request_shape(llm, cfg):
    llm.client = StubClient([GOOD])
    proposal = llm.propose(Extraction("image", "Original filename: a.png", images=[b"png-bytes"]))
    assert (proposal.name, proposal.tag, proposal.confidence) == ("acme-bill", "finance", 0.8)
    call = llm.client.calls[0]
    assert call["model"] == "gemma3:12b"
    assert call["keep_alive"] == -1
    assert call["options"] == {"temperature": 0.2, "num_ctx": 8192}
    schema = call["format"]
    assert schema["properties"]["tag"]["enum"] == cfg.tags
    assert set(schema["required"]) == {"name", "tag", "confidence", "section", "course", "unit_title"}
    messages = call["messages"]
    assert messages[0]["role"] == "system" and messages[0]["content"].startswith(SYSTEM_PROMPT)
    assert [m["role"] for m in messages[1:9]] == ["user", "assistant"] * 4  # four few-shot pairs
    assert json.loads(messages[2]["content"])["name"] == "acme-power-electric-bill-2026-09-14"
    assert messages[-1]["images"] == [b"png-bytes"]


def test_retries_then_succeeds(llm):
    llm.client = StubClient([httpx.ReadTimeout("slow"), "not json", GOOD])
    assert llm.propose(Extraction("text", "h", text="t")).name == "acme-bill"
    assert len(llm.client.calls) == 3


def test_gives_up_after_three_attempts(llm):
    llm.client = StubClient(["{}", "{}", "{}", GOOD])
    with pytest.raises(LLMError):
        llm.propose(Extraction("text", "h", text="t"))
    assert len(llm.client.calls) == 3


def test_connection_error_means_unavailable(llm):
    llm.client = StubClient([ConnectionError("refused")])
    with pytest.raises(OllamaUnavailable):
        llm.propose(Extraction("text", "h", text="t"))
    assert len(llm.client.calls) == 1


def test_confidence_is_clamped(llm):
    llm.client = StubClient([json.dumps({"name": "x-y-z", "tag": "other", "confidence": 7})])
    assert llm.propose(Extraction("text", "h", text="t")).confidence == 1.0


def test_few_shot_tags_outside_the_list_fall_back(cfg):
    cfg.tags = ["finance", "other"]
    llm = LLM(cfg)
    answers = [json.loads(m["content"]) for m in llm._messages(Extraction("text", "h", text="t"))
               if m["role"] == "assistant"]
    assert {a["tag"] for a in answers} <= {"finance", "other"}


def test_school_fields_are_returned(llm):
    answer = {"name": "x-y-z", "tag": "math", "confidence": 0.9,
              "section": "2.4", "course": "Algebra 2", "unit_title": "Quadratic Functions"}
    llm.client = StubClient([json.dumps(answer)])
    proposal = llm.propose(Extraction("text", "h", text="t"))
    assert (proposal.section, proposal.course, proposal.unit_title) == ("2.4", "Algebra 2", "Quadratic Functions")
