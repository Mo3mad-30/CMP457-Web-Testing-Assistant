"""Live tests: real API calls. Skipped unless RUN_LIVE_TESTS=1 (they use your free-tier quota)."""
import dataclasses
import json
import os

import pytest

from app import config, model_client

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="live test: set RUN_LIVE_TESTS=1 to run",
)

MESSAGES = [
    {"role": "system", "content": "You are a test assistant. Reply with a JSON object only."},
    {"role": "user", "content": 'Return JSON with one key "status" set to "ready".'},
]


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Keep your real data/app.db clean; the evidence run is done separately in Task 8."""
    monkeypatch.setattr(model_client.db, "log_model_call", lambda record, response_text=None, db_path=None: 0)


def _show(label, result):
    print(f"\n[{label}]")
    for a in result.attempts:
        print(
            f"  {a.provider}/{a.model} status={a.status} is_fallback={a.is_fallback} "
            f"tokens={a.prompt_tokens}+{a.completion_tokens} latency={a.latency_ms} ms"
        )
    print(f"  answer: {result.text}")


def test_live_primary_returns_real_tokens_and_latency():
    if not config.settings.groq_api_key:
        pytest.skip("GROQ_API_KEY is not set")
    result = model_client.call_model(MESSAGES, "summarize_selection")
    _show("primary", result)

    assert result.text is not None
    assert isinstance(json.loads(result.text), dict)
    assert result.is_fallback is False
    assert len(result.attempts) == 1
    rec = result.attempts[0]
    assert rec.status == "ok"
    assert rec.prompt_tokens and rec.prompt_tokens > 0
    assert rec.completion_tokens and rec.completion_tokens > 0
    assert rec.latency_ms > 0


def test_live_fallback_to_gemini_when_groq_fails(monkeypatch):
    s = config.settings
    if not (s.gemini_api_key and s.fallback_provider == "gemini" and s.fallback_model_name):
        pytest.skip("Gemini fallback is not configured in .env")
    monkeypatch.setattr(model_client, "RETRY_WAIT_SECONDS", 0)
    monkeypatch.setattr(config, "settings", dataclasses.replace(s, groq_api_key="invalid-key"))

    result = model_client.call_model(MESSAGES, "summarize_selection")
    _show("fallback", result)

    assert result.text is not None
    assert isinstance(json.loads(result.text), dict)
    assert result.is_fallback is True
    assert result.provider == "gemini"
    assert result.fallback_reason == "groq error after retry"
    assert [a.status for a in result.attempts] == ["error", "error", "ok"]
    gemini = result.attempts[2]
    assert gemini.prompt_tokens and gemini.prompt_tokens > 0
    assert gemini.completion_tokens and gemini.completion_tokens > 0