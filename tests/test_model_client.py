import inspect
from app.model_client import ModelResult, call_model
import json
import httpx
from app.model_client import call_groq
from app.model_client import _to_gemini_request, call_gemini
import dataclasses
import pytest
from app import config, model_client
from app.model_client import ProviderOutcome
from app import config, db, model_client

OK = ProviderOutcome("ok", 50, text="{}", prompt_tokens=10, completion_tokens=5)
RATE = ProviderOutcome("rate_limited", 5, error="HTTP 429")
ERR = ProviderOutcome("error", 5, error="HTTP 500")

def test_model_result_defaults():
    r = ModelResult(text=None, provider="groq", model="openai/gpt-oss-120b")
    assert r.is_fallback is False
    assert r.fallback_reason is None
    assert r.attempts == []


def test_attempts_list_is_not_shared_between_results():
    a = ModelResult(text=None, provider="groq", model="m")
    b = ModelResult(text=None, provider="groq", model="m")
    a.attempts.append(object())
    assert b.attempts == []


def test_call_model_signature_matches_plan():
    params = inspect.signature(call_model).parameters
    assert list(params) == ["messages", "purpose", "inspection_id", "json_mode"]
    assert params["inspection_id"].default is None
    assert params["json_mode"].default is True

MESSAGES = [{"role": "user", "content": "Reply in JSON."}]
OK_BODY = {
    "choices": [{"message": {"content": '{"summary": "x"}'}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
}

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_groq_ok_parses_text_tokens_and_sends_expected_request():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    out = call_groq(MESSAGES, "openai/gpt-oss-120b", "secret-key", client=_client(handler))
    assert out.status == "ok"
    assert out.text == '{"summary": "x"}'
    assert (out.prompt_tokens, out.completion_tokens) == (120, 30)
    assert out.latency_ms >= 0
    assert seen["auth"] == "Bearer secret-key"
    assert seen["body"]["model"] == "openai/gpt-oss-120b"
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_groq_json_mode_off_omits_response_format():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    call_groq(MESSAGES, "m", "k", json_mode=False, client=_client(handler))
    assert "response_format" not in seen["body"]


def test_groq_429_is_rate_limited():
    out = call_groq(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(429)))
    assert out.status == "rate_limited"
    assert out.text is None


def test_groq_server_error_is_error():
    out = call_groq(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(500)))
    assert out.status == "error"
    assert out.error == "HTTP 500"


def test_groq_timeout_is_error_without_leaking_key():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    out = call_groq(MESSAGES, "m", "secret-key", client=_client(handler))
    assert out.status == "error"
    assert "secret-key" not in (out.error or "")


def test_groq_unexpected_body_is_error():
    out = call_groq(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(200, json={"oops": 1})))
    assert out.status == "error"
    assert out.error == "unexpected response shape"


def test_groq_empty_text_is_error():
    body = {"choices": [{"message": {"content": ""}}], "usage": {}}
    out = call_groq(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(200, json=body)))
    assert out.status == "error"


def test_groq_missing_key_makes_no_request():
    def handler(request):
        raise AssertionError("no request should be sent without a key")

    out = call_groq(MESSAGES, "m", "", client=_client(handler))
    assert out.status == "error"

GEMINI_OK = {
    "candidates": [{"content": {"parts": [{"text": '{"summary": '}, {"text": '"x"}'}]}}],
    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 10},
}


def test_gemini_request_conversion():
    msgs = [
        {"role": "system", "content": "Be strict."},
        {"role": "user", "content": "Hi, reply in JSON."},
        {"role": "assistant", "content": "{}"},
    ]
    body = _to_gemini_request(msgs, json_mode=True)
    assert body["systemInstruction"] == {"parts": [{"text": "Be strict."}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model"]
    assert body["generationConfig"] == {"responseMimeType": "application/json"}


def test_gemini_ok_parses_text_and_counts_thinking_tokens():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        return httpx.Response(200, json=GEMINI_OK)

    out = call_gemini(MESSAGES, "gemini-2.5-flash", "secret-key", client=_client(handler))
    assert out.status == "ok"
    assert out.text == '{"summary": "x"}'
    assert (out.prompt_tokens, out.completion_tokens) == (100, 30)
    assert seen["url"].endswith("/gemini-2.5-flash:generateContent")
    assert seen["key"] == "secret-key"
    assert "secret-key" not in seen["url"]


def test_gemini_json_mode_off_omits_generation_config():
    assert "generationConfig" not in _to_gemini_request(MESSAGES, json_mode=False)


def test_gemini_without_thinking_tokens_uses_answer_tokens():
    body = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7},
    }
    out = call_gemini(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(200, json=body)))
    assert out.completion_tokens == 7


def test_gemini_429_is_rate_limited():
    out = call_gemini(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(429)))
    assert out.status == "rate_limited"


def test_gemini_503_is_error():
    out = call_gemini(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(503)))
    assert out.status == "error"
    assert out.error == "HTTP 503"


def test_gemini_timeout_is_error_without_leaking_key():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    out = call_gemini(MESSAGES, "m", "secret-key", client=_client(handler))
    assert out.status == "error"
    assert "secret-key" not in (out.error or "")


def test_gemini_blocked_response_without_candidates_is_error():
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    out = call_gemini(MESSAGES, "m", "k", client=_client(lambda r: httpx.Response(200, json=body)))
    assert out.status == "error"


def test_gemini_missing_key_makes_no_request():
    def handler(request):
        raise AssertionError("no request should be sent without a key")

    out = call_gemini(MESSAGES, "m", "", client=_client(handler))
    assert out.status == "error"

@pytest.fixture
def settings(monkeypatch, logged):
    monkeypatch.setattr(model_client, "RETRY_WAIT_SECONDS", 0)  # tests never sleep
    s = dataclasses.replace(
        config.settings,
        model_provider="groq", model_name="primary-model",
        fallback_provider="gemini", fallback_model_name="fallback-model",
        groq_api_key="groq-secret", gemini_api_key="gemini-secret",
    )
    monkeypatch.setattr(config, "settings", s)
    return s


def _script(monkeypatch, groq=(), gemini=()):
    """Fake both providers; each call pops the next scripted outcome and is recorded."""
    calls = {"groq": [], "gemini": []}
    queues = {"groq": list(groq), "gemini": list(gemini)}

    def make(name):
        def fake(messages, model, api_key, json_mode=True, **kwargs):
            calls[name].append({"model": model, "key": api_key, "json_mode": json_mode})
            return queues[name].pop(0)
        return fake

    monkeypatch.setattr(model_client, "call_groq", make("groq"))
    monkeypatch.setattr(model_client, "call_gemini", make("gemini"))
    return calls


def test_success_on_first_try(settings, monkeypatch):
    calls = _script(monkeypatch, groq=[OK])
    r = model_client.call_model(MESSAGES, "summarize_selection", "insp-1")
    assert r.text == "{}"
    assert (r.provider, r.model, r.is_fallback, r.fallback_reason) == ("groq", "primary-model", False, None)
    assert len(calls["groq"]) == 1 and calls["gemini"] == []
    rec = r.attempts[0]
    assert (rec.status, rec.purpose, rec.inspection_id) == ("ok", "summarize_selection", "insp-1")
    assert (rec.prompt_tokens, rec.completion_tokens, rec.latency_ms) == (10, 5, 50)


def test_retry_succeeds_without_fallback(settings, monkeypatch):
    calls = _script(monkeypatch, groq=[RATE, OK])
    r = model_client.call_model(MESSAGES, "p")
    assert r.text == "{}" and r.is_fallback is False
    assert len(calls["groq"]) == 2 and calls["gemini"] == []
    assert [a.status for a in r.attempts] == ["rate_limited", "ok"]


def test_fallback_after_failed_retry(settings, monkeypatch):
    calls = _script(monkeypatch, groq=[RATE, RATE], gemini=[OK])
    r = model_client.call_model(MESSAGES, "p")
    assert r.text == "{}"
    assert (r.provider, r.model, r.is_fallback) == ("gemini", "fallback-model", True)
    assert r.fallback_reason == "groq rate_limited after retry"
    assert calls["gemini"][0]["model"] == "fallback-model"
    assert [a.is_fallback for a in r.attempts] == [False, False, True]
    assert r.attempts[2].fallback_reason == "groq rate_limited after retry"
    assert r.attempts[0].fallback_reason is None


def test_no_fallback_configured_returns_none_text(settings, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(settings, fallback_provider="", fallback_model_name=""))
    calls = _script(monkeypatch, groq=[ERR, ERR])
    r = model_client.call_model(MESSAGES, "p")
    assert r.text is None and r.is_fallback is False
    assert len(r.attempts) == 2 and calls["gemini"] == []


def test_everything_fails_keeps_all_attempts(settings, monkeypatch):
    _script(monkeypatch, groq=[ERR, ERR], gemini=[RATE])
    r = model_client.call_model(MESSAGES, "p")
    assert r.text is None and r.is_fallback is False
    assert [a.status for a in r.attempts] == ["error", "error", "rate_limited"]
    assert r.attempts[2].is_fallback is True


def test_each_provider_gets_its_own_key_and_keys_never_appear_in_records(settings, monkeypatch):
    calls = _script(monkeypatch, groq=[ERR, ERR], gemini=[OK])
    r = model_client.call_model(MESSAGES, "p")
    assert calls["groq"][0]["key"] == "groq-secret"
    assert calls["gemini"][0]["key"] == "gemini-secret"
    dumped = str(r.attempts) + str(r)
    assert "groq-secret" not in dumped and "gemini-secret" not in dumped


def test_json_mode_is_passed_through(settings, monkeypatch):
    calls = _script(monkeypatch, groq=[OK])
    model_client.call_model(MESSAGES, "p", json_mode=False)
    assert calls["groq"][0]["json_mode"] is False


def test_unknown_provider_does_not_crash(settings, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(
        settings, model_provider="nope", fallback_provider="", fallback_model_name=""))
    r = model_client.call_model(MESSAGES, "p")
    assert r.text is None
    assert [a.status for a in r.attempts] == ["error", "error"]

@pytest.fixture
def logged(monkeypatch):
    """Replace db.log_model_call with a list, so tests never touch the real database."""
    rows = []

    def fake(record, response_text=None, db_path=None):
        rows.append((record, response_text))
        return len(rows)

    monkeypatch.setattr(model_client.db, "log_model_call", fake)
    return rows

def test_success_logs_one_row_with_response_text(settings, logged, monkeypatch):
    _script(monkeypatch, groq=[OK])
    r = model_client.call_model(MESSAGES, "summarize_selection", "insp-1")
    assert [rec for rec, _ in logged] == r.attempts
    assert [text for _, text in logged] == ["{}"]


def test_fallback_path_logs_every_attempt_text_only_on_success(settings, logged, monkeypatch):
    _script(monkeypatch, groq=[RATE, RATE], gemini=[OK])
    r = model_client.call_model(MESSAGES, "p")
    assert [rec for rec, _ in logged] == r.attempts
    assert [text for _, text in logged] == [None, None, "{}"]
    assert [rec.is_fallback for rec, _ in logged] == [False, False, True]


def test_failed_calls_are_logged_too(settings, logged, monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(settings, fallback_provider="", fallback_model_name=""))
    _script(monkeypatch, groq=[ERR, ERR])
    model_client.call_model(MESSAGES, "p")
    assert [(rec.status, text) for rec, text in logged] == [("error", None), ("error", None)]


def test_logging_failure_does_not_break_the_call(settings, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(model_client.db, "log_model_call", broken)
    _script(monkeypatch, groq=[OK])
    r = model_client.call_model(MESSAGES, "p")
    assert r.text == "{}"


def test_attempts_are_stored_in_the_real_database(isolated_settings, monkeypatch):
    monkeypatch.setattr(model_client, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(config, "settings", dataclasses.replace(
        config.settings, model_provider="groq", model_name="primary-model",
        fallback_provider="gemini", fallback_model_name="fallback-model"))
    _script(monkeypatch, groq=[RATE, RATE], gemini=[OK])
    db.init_db()

    model_client.call_model(MESSAGES, "summarize_selection")

    rows = db.list_model_calls()
    assert [row["status"] for row in rows] == ["ok", "rate_limited", "rate_limited"]  # newest first
    assert rows[0]["is_fallback"] is True
    with db.connect() as conn:
        texts = [row[0] for row in conn.execute("SELECT response_text FROM model_calls ORDER BY id")]
    assert texts == [None, None, "{}"]