import inspect

from app.model_client import ModelResult, call_model


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