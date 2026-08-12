"""The language model backends, spoken to over plain HTTP.

Two of them: Gemini, which is what the scheduled job uses, and Ollama, which is
what you use locally to iterate on the prompt without spending quota. Both
expose one method, so the rest of the agent never learns which it got.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
OLLAMA_HOST = "http://localhost:11434"
# Ollama defaults to 4096 tokens of context and drops the overflow without
# saying so -- on the default the local model answered from a fragment of the
# instructions, in prose, three attempts a run.
#
# This has to hold the prompt and the answer together, with room for the
# thinking qwen3 does in between, and the prompt is not a fixed size: it grew
# from ~11,000 tokens to ~23,500 the day `candidate_limit` went 20 -> 40 and the
# recap of previous editions arrived. **Raising candidate_limit means raising
# this**, or the local backend silently returns to answering from a fragment.
OLLAMA_CONTEXT = 32768
# One real digest at that context measured 247 seconds on a warm model, and the
# first call of a run also pays to load it. The old 300 was a timeout, not a
# limit worth enforcing: nothing local is waiting on this.
OLLAMA_TIMEOUT = 900

RETRIES = 3
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
# A published digest runs to roughly 1400 tokens of visible text, so 4096 looks
# generous -- but on 2026-08-06 and 2026-08-08 the answer still arrived cut off
# mid-array, on days whose input was identical to days that worked. The budget
# is shared with whatever reasoning the model does before it answers, and that
# varies run to run. Doubling it buys room for the thinking, not for the digest.
# Kept deliberately modest: a value above what the model accepts would be a 400,
# and `_post` does not retry those, which would break every day instead of some.
MAX_OUTPUT_TOKENS = 8192
# Ways of saying "it finished because it was done", lowercased.
NORMAL_STOPS = frozenset({"completed", "complete", "stop", "end_turn", "finished"})


class LLMError(RuntimeError):
    """Raised when a model cannot be reached, or answers with nothing usable."""


class LLM(Protocol):
    name: str

    def generate(self, prompt: str, *, system: str = "") -> str: ...


class Gemini:
    """https://ai.google.dev/gemini-api/docs/quickstart"""

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        endpoint: str = GEMINI_ENDPOINT,
        timeout: int = 90,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        temperature: float = 0.4,
        on_note: Callable[[str], None] | None = None,
    ):
        if not api_key:
            raise LLMError("no Gemini API key; set GEMINI_API_KEY")
        self.name = f"gemini:{model}"
        self._model = model
        self._key = api_key
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._note = on_note or (lambda _: None)

    def generate(self, prompt: str, *, system: str = "") -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "input": prompt,
            "generation_config": {
                "temperature": self._temperature,
                "max_output_tokens": self._max_output_tokens,
            },
        }
        if system:
            body["system_instruction"] = system

        payload = _post(
            self._endpoint,
            body,
            headers={"x-goog-api-key": self._key},
            timeout=self._timeout,
        )
        reason = _stop_reason(payload)
        text = _gemini_text(payload)
        if not text:
            why = f" ({reason})" if reason else ""
            raise LLMError(
                f"Gemini returned no text{why}: {json.dumps(payload)[:400]}"
            )
        # An answer can be cut off and still carry usable text, so hand it back
        # either way -- but say so, because a caller parsing it deserves to know.
        if reason:
            self._note(f"generation stopped early: {reason}")
        return text


class Ollama:
    """A local model, for developing the prompt without touching the quota."""

    def __init__(
        self,
        model: str,
        *,
        host: str = OLLAMA_HOST,
        timeout: int = OLLAMA_TIMEOUT,
        temperature: float = 0.4,
        context: int = OLLAMA_CONTEXT,
    ):
        self.name = f"ollama:{model}"
        self._model = model
        self._url = f"{host.rstrip('/')}/api/generate"
        self._timeout = timeout
        self._temperature = temperature
        self._context = context

    def generate(self, prompt: str, *, system: str = "") -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self._temperature, "num_ctx": self._context},
        }
        if system:
            body["system"] = system

        payload = _post(self._url, body, headers={}, timeout=self._timeout)
        text = str(payload.get("response", "")).strip()
        if not text:
            raise LLMError(f"Ollama returned no text: {json.dumps(payload)[:400]}")
        return text


def from_environment(
    *,
    backend: str = "auto",
    model: str = "",
    ollama_model: str = "qwen3:8b",
    on_note: Callable[[str], None] | None = None,
) -> LLM:
    """Pick a backend: an explicit one, or whichever the environment can serve."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()

    if backend == "gemini" or (backend == "auto" and key):
        return Gemini(model, key, on_note=on_note)
    if backend in ("ollama", "auto"):
        return Ollama(ollama_model)
    raise LLMError(f"unknown backend: {backend!r}")


def _stop_reason(payload: dict[str, Any]) -> str:
    """Why generation ended, when the answer bothers to say and it is not "done".

    The field moved around between API shapes, so look everywhere it has been
    seen. An empty string means nothing worth reporting.
    """
    details = payload.get("incomplete_details")
    if isinstance(details, dict) and details.get("reason"):
        return str(details["reason"])

    for candidate in payload.get("candidates") or []:
        reason = candidate.get("finishReason") or candidate.get("finish_reason")
        if reason and str(reason).lower() not in NORMAL_STOPS:
            return str(reason)

    status = payload.get("status")
    if status and str(status).lower() not in NORMAL_STOPS:
        return str(status)

    return ""


def _gemini_text(payload: dict[str, Any]) -> str:
    """Pull the answer out of an interaction, whichever shape it arrives in."""
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()

    for step in reversed(payload.get("steps") or []):
        blocks = step.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type", "text") == "text"
        ).strip()
        if text:
            return text

    # The older generateContent shape, in case the endpoint is pointed back at it.
    for candidate in payload.get("candidates") or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if text:
            return text

    return ""


def _post(
    url: str, body: dict[str, Any], *, headers: dict[str, str], timeout: int
) -> dict[str, Any]:
    """POST JSON, retrying the failures that tend to pass on their own."""
    request_headers = {"Content-Type": "application/json", **headers}
    data = json.dumps(body).encode("utf-8")
    last: Exception | None = None

    for attempt in range(1, RETRIES + 1):
        request = urllib.request.Request(url, data=data, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            # Generous: a 429 says which quota ran out and when it resets, and
            # that is the whole diagnosis. Cutting at 300 characters truncated
            # the message exactly before the metric name.
            detail = error.read().decode("utf-8", "replace")[:900]
            last = LLMError(f"HTTP {error.code} from {url}: {detail}")
            if error.code not in RETRY_STATUSES:
                raise last from error
        except urllib.error.URLError as error:
            last = LLMError(f"could not reach {url}: {error.reason}")
        # Not covered by the line above: a socket that times out mid-read raises
        # TimeoutError, an OSError urllib does not wrap. Uncaught it escapes
        # past digest.build's fallback and costs the day its post entirely.
        except TimeoutError as error:
            last = LLMError(f"could not reach {url}: timed out: {error}")
        except json.JSONDecodeError as error:
            raise LLMError(f"{url} did not answer with JSON: {error}") from error

        if attempt < RETRIES:
            time.sleep(2**attempt)

    raise last or LLMError(f"{url} failed for reasons unknown")
