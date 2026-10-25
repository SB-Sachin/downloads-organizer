from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass

import httpx
import ollama

from .config import Config
from .extract import Extraction

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120
RETRIES = 3
DOWN_RETRY_SECONDS = 30

SYSTEM_PROMPT = (
    "You name and tag downloaded files. Read the content and the original filename. "
    "Return JSON only. name: 3 to 6 lowercase words joined by hyphens, ASCII letters and "
    "digits only, maximum 60 characters, no extension. Describe the specific content, such "
    "as the title, subject, sender, or purpose. Never use a generic word like document, "
    "file, image, or untitled alone. Include a date only when the content shows one, "
    "formatted yyyy-mm-dd. tag: choose exactly one value from the allowed list. "
    "confidence: your certainty from 0 to 1."
    " For class notes, homework, worksheets, and textbook pages, also fill three fields "
    "exactly as the page shows them: section: the section, lesson, or exercise number such as "
    "2.4, with its dot; course: the class name such as Algebra 2, without the teacher's name "
    "or class period; unit_title: the title at the top of the page, such as Quadratic "
    "Functions, in title case. Leave a field empty when the page does not show it, and never "
    "invent a number. For every other file, leave all three empty."
)

FEW_SHOT = [
    (
        "Original filename: statement_0914.pdf\nExtension: .pdf\nSize: 84.2 KB\n"
        "Modified: 2026-09-15 08:12\n\nContent (pdf text):\nAcme Power\nElectric Bill\n"
        "Statement date: September 14, 2026\nAccount number ending 4471\nAmount due: $132.18",
        {"name": "acme-power-electric-bill-2026-09-14", "tag": "finance", "confidence": 0.95,
         "section": "", "course": "", "unit_title": ""},
    ),
    (
        "Original filename: Screenshot 2026-10-02 at 9.41.07 PM.png\nExtension: .png\n"
        "Size: 412.0 KB\nModified: 2026-10-02 21:41\n\nContent (image): a screenshot of a "
        "terminal window showing a Python traceback that ends in ImportError.",
        {"name": "python-importerror-terminal-screenshot", "tag": "code", "confidence": 0.9,
         "section": "", "course": "", "unit_title": ""},
    ),
    (
        "Original filename: reqs.txt\nExtension: .txt\nSize: 3.1 KB\nModified: 2026-08-30 17:05\n\n"
        "Content (text):\nCooking Merit Badge Requirements\n1. Health and safety. Do the following:\n"
        "a. Explain to your counselor the most likely hazards you may encounter while cooking.",
        {"name": "cooking-merit-badge-requirements", "tag": "scouts", "confidence": 0.9,
         "section": "", "course": "", "unit_title": ""},
    ),
    (
        "Original filename: Scan 12.pdf\nExtension: .pdf\nSize: 1.2 MB\nModified: 2026-10-14 16:20\n\n"
        "Content (pdf text):\nQuadratic Functions\nAlgebra 2 - Mr. Lee - Period 3\n"
        "2.4 Completing the Square\n1. Rewrite x^2 + 6x + 5 in vertex form.",
        {"name": "algebra-2-quadratic-functions-2-4", "tag": "math", "confidence": 0.9,
         "section": "2.4", "course": "Algebra 2", "unit_title": "Quadratic Functions"},
    ),
]


class OllamaUnavailable(Exception):
    """The server cannot be reached. The caller keeps the file queued."""


class LLMError(Exception):
    """The model call failed after all retries."""


@dataclass
class Proposal:
    name: str
    tag: str
    confidence: float
    section: str = ""
    course: str = ""
    unit_title: str = ""


class LLM:
    def __init__(self, cfg: Config, backoff: float = 2.0):
        self.cfg = cfg
        self.backoff = backoff
        self.client = ollama.Client(host=cfg.ollama_host, timeout=TIMEOUT_SECONDS)
        self.schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "tag": {"type": "string", "enum": list(cfg.tags)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "section": {"type": "string"},
                "course": {"type": "string"},
                "unit_title": {"type": "string"},
            },
            "required": ["name", "tag", "confidence", "section", "course", "unit_title"],
        }

    def _messages(self, extraction: Extraction) -> list[dict]:
        system = f"{SYSTEM_PROMPT}\nAllowed tags: {', '.join(self.cfg.tags)}."
        messages: list[dict] = [{"role": "system", "content": system}]
        for user, answer in FEW_SHOT:
            # The examples only teach the format, so keep their tags inside the allowed list.
            answer = {**answer, "tag": answer["tag"] if answer["tag"] in self.cfg.tags else self.cfg.fallback_tag}
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": json.dumps(answer)})
        final: dict = {"role": "user", "content": extraction.prompt()}
        if extraction.images:
            final["images"] = list(extraction.images)
        messages.append(final)
        return messages

    def _chat(self, messages: list[dict]) -> str:
        response = self.client.chat(
            model=self.cfg.model,
            messages=messages,
            format=self.schema,
            keep_alive=self.cfg.keep_alive,
            options={"temperature": 0.2, "num_ctx": 8192},
        )
        return response["message"]["content"]

    def propose(self, extraction: Extraction, stop: threading.Event | None = None) -> Proposal:
        stop = stop or threading.Event()
        messages = self._messages(extraction)
        last_error: Exception | None = None
        for attempt in range(1, RETRIES + 1):
            try:
                data = json.loads(self._chat(messages))
                confidence = min(1.0, max(0.0, float(data["confidence"])))
                return Proposal(
                    str(data["name"]), str(data["tag"]), confidence,
                    str(data.get("section") or ""), str(data.get("course") or ""),
                    str(data.get("unit_title") or ""),
                )
            except (ConnectionError, httpx.ConnectError) as exc:
                raise OllamaUnavailable(str(exc)) from exc
            except (ollama.ResponseError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                log.warning("model call failed (attempt %d of %d): %s", attempt, RETRIES, exc)
            if attempt < RETRIES and stop.wait(self.backoff * 2 ** (attempt - 1)):
                break
        raise LLMError(f"model call failed after {RETRIES} attempts: {last_error}")

    def is_up(self) -> bool:
        try:
            self.client.list()
            return True
        except Exception:
            return False

    def installed_models(self) -> list[str]:
        return [m["model"] for m in self.client.list()["models"]]

    def model_installed(self) -> bool:
        wanted = self.cfg.model if ":" in self.cfg.model else f"{self.cfg.model}:latest"
        return wanted in self.installed_models()

    def loaded_models(self) -> list[str]:
        return [m["model"] for m in self.client.ps()["models"]]

    def wait_until_up(self, stop: threading.Event, interval: float = DOWN_RETRY_SECONDS) -> bool:
        """Block until the server answers. Return False if stop fires first."""
        warned = False
        while not stop.is_set():
            if self.is_up():
                if warned:
                    log.info("Ollama is reachable again at %s", self.cfg.ollama_host)
                return True
            if not warned:
                log.warning("Ollama is not reachable at %s, retrying every %.0f s", self.cfg.ollama_host, interval)
                warned = True
            stop.wait(interval)
        return False
