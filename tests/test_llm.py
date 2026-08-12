import io
import json
import urllib.error

import pytest

from agent import llm


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def responder(*outcomes):
    """Answer each call with the next outcome, raising the ones that are errors."""
    remaining = list(outcomes)
    calls = []

    def urlopen(request, timeout=None):
        calls.append(request)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode("utf-8"))

    urlopen.calls = calls
    return urlopen


def http_error(code, body=b"nope"):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)


def test_reads_the_text_out_of_an_interaction(monkeypatch):
    payload = {
        "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": "Hello."}]}],
    }
    monkeypatch.setattr("urllib.request.urlopen", responder(payload))

    assert llm.Gemini("gemini-3.6-flash", "key").generate("hi") == "Hello."


def test_reads_the_output_text_shortcut_when_it_is_there(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", responder({"output_text": " Hi "}))
    assert llm.Gemini("m", "key").generate("hi") == "Hi"


def test_reads_the_older_generate_content_shape(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": "Legacy."}]}}]}
    monkeypatch.setattr("urllib.request.urlopen", responder(payload))
    assert llm.Gemini("m", "key").generate("hi") == "Legacy."


def test_an_answer_with_no_text_is_an_error(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", responder({"steps": []}))
    with pytest.raises(llm.LLMError, match="no text"):
        llm.Gemini("m", "key").generate("hi")


def test_an_answer_cut_short_is_reported_but_still_returned(monkeypatch):
    payload = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "steps": [{"content": [{"type": "text", "text": "half an ans"}]}],
    }
    monkeypatch.setattr("urllib.request.urlopen", responder(payload))
    notes = []

    text = llm.Gemini("m", "key", on_note=notes.append).generate("hi")

    assert text == "half an ans"
    assert notes and "max_output_tokens" in notes[0]


def test_the_legacy_finish_reason_is_reported_too(monkeypatch):
    payload = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "x"}]}}]}
    monkeypatch.setattr("urllib.request.urlopen", responder(payload))
    notes = []

    llm.Gemini("m", "key", on_note=notes.append).generate("hi")

    assert notes and "MAX_TOKENS" in notes[0]


def test_a_normal_answer_is_reported_as_nothing(monkeypatch):
    payload = {
        "status": "completed",
        "steps": [{"content": [{"type": "text", "text": "all of it"}]}],
    }
    monkeypatch.setattr("urllib.request.urlopen", responder(payload))
    notes = []

    llm.Gemini("m", "key", on_note=notes.append).generate("hi")

    assert notes == []


def test_an_answer_with_no_text_says_why_it_stopped(monkeypatch):
    payload = {"status": "incomplete", "incomplete_details": {"reason": "safety"}, "steps": []}
    monkeypatch.setattr("urllib.request.urlopen", responder(payload))

    with pytest.raises(llm.LLMError, match="safety"):
        llm.Gemini("m", "key").generate("hi")


def test_sends_the_key_the_model_and_the_system_instruction(monkeypatch):
    urlopen = responder({"output_text": "ok"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    llm.Gemini("gemini-3.6-flash", "secret").generate("the prompt", system="be brief")

    request = urlopen.calls[0]
    body = json.loads(request.data)
    assert request.get_header("X-goog-api-key") == "secret"
    assert body["model"] == "gemini-3.6-flash"
    assert body["input"] == "the prompt"
    assert body["system_instruction"] == "be brief"


def test_the_request_carries_the_token_budget_it_was_given(monkeypatch):
    urlopen = responder({"output_text": "ok"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    llm.Gemini("m", "key", max_output_tokens=1234).generate("hi")

    config = json.loads(urlopen.calls[0].data)["generation_config"]
    assert config["max_output_tokens"] == 1234


def test_the_default_budget_leaves_room_for_a_ten_story_digest(monkeypatch):
    urlopen = responder({"output_text": "ok"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    llm.Gemini("m", "key").generate("hi")

    config = json.loads(urlopen.calls[0].data)["generation_config"]
    assert config["max_output_tokens"] == llm.MAX_OUTPUT_TOKENS
    # The published digests run to ~1400 tokens of visible text. Anything close
    # to that leaves nothing for reasoning, which is what truncated 2026-08-06.
    assert llm.MAX_OUTPUT_TOKENS >= 8192


def test_retries_a_rate_limit_and_then_succeeds(monkeypatch):
    urlopen = responder(http_error(429), {"output_text": "second time lucky"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert llm.Gemini("m", "key").generate("hi") == "second time lucky"
    assert len(urlopen.calls) == 2


def test_gives_up_after_the_last_retry(monkeypatch):
    urlopen = responder(*[http_error(503)] * llm.RETRIES)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(llm.LLMError, match="HTTP 503"):
        llm.Gemini("m", "key").generate("hi")
    assert len(urlopen.calls) == llm.RETRIES


def test_does_not_retry_a_bad_request(monkeypatch):
    urlopen = responder(http_error(400, b"bad model"))
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(llm.LLMError, match="bad model"):
        llm.Gemini("m", "key").generate("hi")
    assert len(urlopen.calls) == 1


def test_a_missing_key_is_refused_up_front():
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        llm.Gemini("m", "")


def test_ollama_speaks_its_own_shape(monkeypatch):
    urlopen = responder({"response": "  local answer  "})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert llm.Ollama("qwen3:8b").generate("hi", system="s") == "local answer"

    body = json.loads(urlopen.calls[0].data)
    assert body == {
        "model": "qwen3:8b",
        "prompt": "hi",
        "stream": False,
        "options": {"temperature": 0.4, "num_ctx": llm.OLLAMA_CONTEXT},
        "system": "s",
    }


def test_a_read_that_times_out_is_a_model_failure_like_any_other(monkeypatch):
    # A socket timing out mid-read raises TimeoutError, which is an OSError and
    # *not* a URLError, so it used to escape _post uncaught. That skips
    # digest.build's fallback entirely: instead of publishing the reading list,
    # the run dies with a traceback and the day gets no post at all.
    urlopen = responder(*[TimeoutError("timed out")] * llm.RETRIES)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(llm.LLMError, match="timed out"):
        llm.Gemini("m", "key").generate("hi")
    assert len(urlopen.calls) == llm.RETRIES


def test_a_timeout_that_passes_on_the_retry_still_answers(monkeypatch):
    urlopen = responder(TimeoutError("timed out"), {"output_text": "second time lucky"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert llm.Gemini("m", "key").generate("hi") == "second time lucky"


def test_ollama_is_given_long_enough_to_answer(monkeypatch):
    # Measured on this machine: one real digest prompt at OLLAMA_CONTEXT took
    # 247 seconds with the model already loaded. The old 300-second default
    # timed out on the first call of a run, which also pays to load the model.
    urlopen = responder({"response": "ok"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    seen = {}

    def watch(request, timeout=None):
        seen["timeout"] = timeout
        return urlopen(request, timeout=timeout)

    monkeypatch.setattr("urllib.request.urlopen", watch)
    llm.Ollama("qwen3:8b").generate("hi")

    assert seen["timeout"] == llm.OLLAMA_TIMEOUT
    assert llm.OLLAMA_TIMEOUT >= 600


def test_ollama_asks_for_a_context_that_fits_the_whole_prompt(monkeypatch):
    # Ollama defaults to 4096 tokens and silently drops whatever does not fit.
    # Since the agent began reading the linked articles the digest prompt runs
    # to ~11k tokens, so the local model stopped seeing the instructions it was
    # meant to follow and answered with prose. That cost this backend the only
    # thing it is for: iterating on the prompt without spending Gemini quota.
    urlopen = responder({"response": "ok"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    llm.Ollama("qwen3:8b").generate("hi")

    options = json.loads(urlopen.calls[0].data)["options"]
    assert options["num_ctx"] == llm.OLLAMA_CONTEXT
    # This has to hold the prompt *and* the answer, and the prompt grew twice in
    # one day. Measured 2026-08-11: 40 enriched candidates plus a recap of the
    # last two editions make a 94,032-character prompt, ~23,500 tokens. A digest
    # is ~1,200 more of visible answer, before qwen3 does any thinking.
    #
    # Raising `candidate_limit` in config.toml raises this. The first version of
    # the twice-weekly settings did not, which left ~1,000 tokens for a 1,200
    # token answer and put the local backend straight back into the failure it
    # had been fixed out of that morning.
    assert llm.OLLAMA_CONTEXT >= 28672


def test_the_backend_follows_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    assert llm.from_environment(model="m").name == "gemini:m"

    monkeypatch.delenv("GEMINI_API_KEY")
    assert llm.from_environment(model="m", ollama_model="qwen3:8b").name == "ollama:qwen3:8b"


def test_asking_for_gemini_without_a_key_is_an_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        llm.from_environment(backend="gemini", model="m")
