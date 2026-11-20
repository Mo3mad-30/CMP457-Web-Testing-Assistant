import inspect
from app.model_client import ModelResult, call_model
import json
import httpx
from app.model_client import call_groq


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