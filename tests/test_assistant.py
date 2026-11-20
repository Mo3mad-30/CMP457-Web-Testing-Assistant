"""Task 7b: Ask model (assistant + /ask route). call_model is faked; storage is temporary."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import assistant, db, main
from app.model_client import ModelResult
from shared.schemas import Inspection, ModelCallRecord, Selection

# Every test gets its own data folder and database (invalid answers are logged to model_calls).
pytestmark = pytest.mark.usefixtures("isolated_settings")

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample_inspection.json"

GOOD = json.dumps({
    "summary": "Username and password fields of the login form.",
    "referenced_element_ids": ["el-001", "el-002"],
    "suggested_next_action": "Draft a negative login test.",
    "clarifying_questions": [],
})
BAD = "not json at all"


def load_sample() -> Inspection:
    return Inspection.model_validate_json(SAMPLE.read_text(encoding="utf-8"))


def make_selection(ids) -> Selection:
    return Selection(
        inspection_id="insp-0001", element_ids=list(ids),
        goal="verify login rejects a wrong password", created_at=datetime.now(timezone.utc),
    )


def record(status: str, provider: str = "groq", is_fallback: bool = False, reason: str | None = None):
    return ModelCallRecord(
        provider=provider, model="m", purpose="summarize_selection", inspection_id="insp-0001",
        prompt_tokens=10, completion_tokens=5, latency_ms=100, status=status,
        is_fallback=is_fallback, fallback_reason=reason, created_at=datetime.now(timezone.utc),
    )


def result(text, *statuses, provider="groq", is_fallback=False, reason=None) -> ModelResult:
    return ModelResult(
        text=text, provider=provider, model="m", is_fallback=is_fallback, fallback_reason=reason,
        attempts=[record(s) for s in statuses],
    )


def script(monkeypatch, *results):
    """Fake call_model: each call pops the next scripted ModelResult and records its arguments."""
    calls, queue = [], list(results)

    def fake(messages, purpose, inspection_id=None, json_mode=True):
        calls.append({"messages": messages, "purpose": purpose, "inspection_id": inspection_id})
        return queue.pop(0)

    monkeypatch.setattr(assistant.model_client, "call_model", fake)
    return calls


def test_valid_answer_needs_one_call(monkeypatch):
    calls = script(monkeypatch, result(GOOD, "ok"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001", "el-002"]))
    assert ask.suggestion is not None and ask.errors == []
    assert len(calls) == 1
    assert calls[0]["purpose"] == "summarize_selection"
    assert calls[0]["inspection_id"] == "insp-0001"
    assert [a.status for a in ask.result.attempts] == ["ok"]


def test_invalid_answer_is_retried_once_with_the_errors_listed(monkeypatch):
    calls = script(monkeypatch, result(BAD, "ok"), result(GOOD, "ok"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001", "el-002"]))
    assert ask.suggestion is not None and ask.errors == []
    assert len(calls) == 2
    retry = calls[1]["messages"]
    assert [m["role"] for m in retry] == ["system", "user", "assistant", "user"]
    assert "not valid JSON" in retry[3]["content"]
    assert [a.status for a in ask.result.attempts] == ["ok", "invalid_output", "ok"]


def test_invalid_twice_reports_invalid_output(monkeypatch):
    calls = script(monkeypatch, result(BAD, "ok"), result(BAD, "ok"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001"]))
    assert ask.suggestion is None
    assert ask.errors[0].startswith("Invalid output")
    assert len(calls) == 2
    assert [a.status for a in ask.result.attempts] == ["ok", "invalid_output", "ok", "invalid_output"]


def test_no_model_answer_is_reported_without_a_retry(monkeypatch):
    calls = script(monkeypatch, result(None, "error", "error", "rate_limited"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001"]))
    assert ask.suggestion is None
    assert "No model answered" in ask.errors[0]
    assert len(calls) == 1
    assert len(ask.result.attempts) == 3


def test_retry_that_gets_no_answer_keeps_the_first_attempt(monkeypatch):
    script(monkeypatch, result(BAD, "ok"), result(None, "error", "error"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001"]))
    assert ask.suggestion is None
    assert "retry" in ask.errors[0]
    assert [a.status for a in ask.result.attempts] == ["ok", "invalid_output", "error", "error"]


def test_fallback_information_reaches_the_result(monkeypatch):
    script(monkeypatch, result(GOOD, "error", "error", "ok", provider="gemini",
                               is_fallback=True, reason="groq error after retry"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001", "el-002"]))
    assert ask.result.is_fallback is True
    assert ask.result.fallback_reason == "groq error after retry"
    assert ask.suggestion is not None


def test_validation_warnings_are_passed_on(monkeypatch):
    script(monkeypatch, result(GOOD, "ok"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001"]))  # answer also cites el-002
    assert ask.suggestion is not None
    assert any("el-002" in w for w in ask.warnings)


def test_summarize_selection_unknown_inspection(monkeypatch):
    calls = script(monkeypatch)
    monkeypatch.setattr(assistant.db, "get_inspection", lambda inspection_id: None)
    ask = assistant.summarize_selection("insp-nope")
    assert ask.suggestion is None and "not found" in ask.errors[0]
    assert calls == []


def test_summarize_selection_without_a_saved_selection(monkeypatch):
    calls = script(monkeypatch)
    monkeypatch.setattr(assistant.db, "get_inspection", lambda inspection_id: load_sample())
    monkeypatch.setattr(assistant.db, "get_latest_selection", lambda inspection_id: None)
    ask = assistant.summarize_selection("insp-0001")
    assert ask.suggestion is None and "Save a selection" in ask.errors[0]
    assert calls == []


def test_summarize_selection_loads_scan_and_selection(monkeypatch):
    script(monkeypatch, result(GOOD, "ok"))
    monkeypatch.setattr(assistant.db, "get_inspection", lambda inspection_id: load_sample())
    monkeypatch.setattr(assistant.db, "get_latest_selection",
                        lambda inspection_id: make_selection(["el-001", "el-002"]))
    ask = assistant.summarize_selection("insp-0001")
    assert ask.suggestion is not None


def test_ask_route_shows_the_validated_answer(monkeypatch):
    monkeypatch.setattr(main, "_sample_selection", make_selection(["el-001", "el-002"]))
    script(monkeypatch, result(GOOD, "ok"))
    client = TestClient(main.app)  # no "with": startup is not run, so no real database is touched
    response = client.post("/inspections/sample/ask")
    assert response.status_code == 200
    assert "model-answer" in response.text
    assert "Username and password fields" in response.text


def test_ask_route_without_a_selection_makes_no_model_call(monkeypatch):
    monkeypatch.setattr(main, "_sample_selection", None)
    calls = script(monkeypatch)
    client = TestClient(main.app)
    response = client.post("/inspections/sample/ask")
    assert response.status_code == 400
    assert "Save a selection" in response.text
    assert calls == []


def _rows():
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT provider, model, purpose, inspection_id, prompt_tokens, completion_tokens, latency_ms,"
            " status, is_fallback, response_text FROM model_calls ORDER BY id")]


def test_invalid_answer_adds_one_invalid_output_row(monkeypatch):
    script(monkeypatch, result(BAD, "ok"), result(GOOD, "ok"))
    assistant.summarize(load_sample(), make_selection(["el-001", "el-002"]))
    # call_model is faked, so only the assistant's own invalid_output row reaches the database
    assert _rows() == [{
        "provider": "groq", "model": "m", "purpose": "summarize_selection", "inspection_id": "insp-0001",
        "prompt_tokens": None, "completion_tokens": None, "latency_ms": 0, "status": "invalid_output",
        "is_fallback": 0, "response_text": BAD,
    }]


def test_invalid_twice_adds_two_invalid_output_rows(monkeypatch):
    other_bad = json.dumps({"summary": "x", "referenced_element_ids": ["el-012"], "suggested_next_action": "y"})
    script(monkeypatch, result(BAD, "ok"), result(other_bad, "ok"))
    assistant.summarize(load_sample(), make_selection(["el-001"]))
    rows = _rows()
    assert [r["status"] for r in rows] == ["invalid_output", "invalid_output"]
    assert [r["response_text"] for r in rows] == [BAD, other_bad]


def test_invalid_output_from_the_fallback_keeps_its_provider(monkeypatch):
    script(monkeypatch, result(BAD, "error", "error", "ok", provider="gemini", is_fallback=True,
                               reason="groq error after retry"), result(GOOD, "ok"))
    ask = assistant.summarize(load_sample(), make_selection(["el-001", "el-002"]))
    invalid = ask.result.attempts[3]
    assert (invalid.provider, invalid.status, invalid.is_fallback) == ("gemini", "invalid_output", True)


def test_a_broken_database_does_not_hide_the_answer(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(assistant.db, "log_model_call", broken)
    script(monkeypatch, result(BAD, "ok"), result(GOOD, "ok"))
    assert assistant.summarize(load_sample(), make_selection(["el-001", "el-002"])).suggestion is not None

