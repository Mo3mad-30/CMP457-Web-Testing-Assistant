"""Storage tests: every test uses its own temporary database and job folder."""
import csv
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db
from shared.schemas import Inspection, ModelCallRecord, Selection

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample_inspection.json"


@pytest.fixture
def dbfile(tmp_path) -> Path:
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def make_scan(tmp_path: Path, inspection_id: str = "insp-test-1", minutes_later: int = 0):
    """A copy of the sample inspection with its own id and JSON file, like the runner would write."""
    insp = Inspection.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    insp = insp.model_copy(update={
        "inspection_id": inspection_id,
        "scanned_at": insp.scanned_at + timedelta(minutes=minutes_later),
    })
    job = tmp_path / "jobs" / inspection_id
    job.mkdir(parents=True)
    json_path = job / "inspection.json"
    json_path.write_text(insp.model_dump_json(indent=2), encoding="utf-8")
    return insp, json_path


def now():
    return datetime.now(timezone.utc)


# --- 3.1 setup ----------------------------------------------------------------

def test_init_db_creates_all_tables_and_is_repeatable(dbfile):
    db.init_db(dbfile)  # second call must not fail
    with sqlite3.connect(dbfile) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"inspections", "elements", "selections", "model_calls", "artifacts"} <= names


# --- 3.2 scans ----------------------------------------------------------------

def test_inspection_round_trip(tmp_path, dbfile):
    insp, json_path = make_scan(tmp_path)
    db.save_inspection(insp, json_path, db_path=dbfile)
    loaded = db.get_inspection("insp-test-1", db_path=dbfile)
    assert loaded == insp


def test_saving_same_inspection_twice_is_refused(tmp_path, dbfile):
    insp, json_path = make_scan(tmp_path)
    db.save_inspection(insp, json_path, db_path=dbfile)
    with pytest.raises(ValueError, match="never overwritten"):
        db.save_inspection(insp, json_path, db_path=dbfile)


def test_elements_index_stores_best_locator(tmp_path, dbfile):
    insp, json_path = make_scan(tmp_path)
    db.save_inspection(insp, json_path, db_path=dbfile)
    with sqlite3.connect(dbfile) as conn:
        rows = conn.execute(
            "SELECT element_id, best_locator, best_match_count FROM elements ORDER BY element_id"
        ).fetchall()
    assert len(rows) == insp.element_count
    assert rows[0] == ("el-001", insp.elements[0].best_locator.value, 1)


def test_unknown_or_missing_file_returns_none(tmp_path, dbfile):
    assert db.get_inspection("insp-nope", db_path=dbfile) is None
    insp, json_path = make_scan(tmp_path)
    db.save_inspection(insp, json_path, db_path=dbfile)
    json_path.unlink()
    assert db.get_inspection("insp-test-1", db_path=dbfile) is None


def test_list_inspections_newest_first(tmp_path, dbfile):
    old, old_path = make_scan(tmp_path, "insp-old", minutes_later=0)
    new, new_path = make_scan(tmp_path, "insp-new", minutes_later=5)
    db.save_inspection(old, old_path, db_path=dbfile)
    db.save_inspection(new, new_path, db_path=dbfile)
    listed = db.list_inspections(db_path=dbfile)
    assert [r["inspection_id"] for r in listed] == ["insp-new", "insp-old"]
    assert {"inspection_id", "url", "title", "scanned_at", "element_count"} <= listed[0].keys()


# --- 3.3 selections -----------------------------------------------------------

def test_latest_selection_wins(tmp_path, dbfile):
    insp, json_path = make_scan(tmp_path)
    db.save_inspection(insp, json_path, db_path=dbfile)
    assert db.get_latest_selection("insp-test-1", db_path=dbfile) is None
    db.save_selection(Selection(inspection_id="insp-test-1", element_ids=["el-001"], goal="first goal",
                                created_at=now()), db_path=dbfile)
    db.save_selection(Selection(inspection_id="insp-test-1", element_ids=["el-001", "el-003"],
                                goal="verify login rejects a wrong password", created_at=now()), db_path=dbfile)
    latest = db.get_latest_selection("insp-test-1", db_path=dbfile)
    assert latest.element_ids == ["el-001", "el-003"]
    assert latest.goal == "verify login rejects a wrong password"


def test_selection_for_unknown_inspection_is_refused(dbfile):
    with pytest.raises(ValueError, match="unknown inspection"):
        db.save_selection(Selection(inspection_id="insp-nope", element_ids=["el-001"], goal="x",
                                    created_at=now()), db_path=dbfile)


# --- 3.4 model calls ----------------------------------------------------------

def make_call(status="ok", is_fallback=False, reason=None, provider="groq"):
    return ModelCallRecord(provider=provider, model="openai/gpt-oss-120b", purpose="summarize_selection",
                           inspection_id="insp-test-1", prompt_tokens=420, completion_tokens=95,
                           latency_ms=850, status=status, is_fallback=is_fallback,
                           fallback_reason=reason, created_at=now())


def test_model_calls_are_logged_newest_first_with_fallback_fields(dbfile):
    db.log_model_call(make_call(status="rate_limited"), db_path=dbfile)
    db.log_model_call(make_call(provider="gemini", is_fallback=True, reason="groq rate_limited after retry"),
                      response_text='{"summary": "..."}', db_path=dbfile)
    calls = db.list_model_calls(db_path=dbfile)
    assert [c["status"] for c in calls] == ["ok", "rate_limited"]
    assert calls[0]["is_fallback"] is True
    assert calls[0]["fallback_reason"] == "groq rate_limited after retry"
    assert "response_text" not in calls[0]


def test_export_model_calls_csv(tmp_path, dbfile):
    db.log_model_call(make_call(), db_path=dbfile)
    db.log_model_call(make_call(status="error"), db_path=dbfile)
    out = db.export_model_calls_csv(tmp_path / "docs" / "model_usage.csv", db_path=dbfile)
    with out.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == db.MODEL_CALL_COLUMNS
    assert [r[rows[0].index("status")] for r in rows[1:]] == ["ok", "error"]


# --- 3.5 app startup ----------------------------------------------------------

def test_app_startup_creates_the_database(isolated_settings):
    from fastapi.testclient import TestClient

    from app import main
    isolated_settings.db_path.unlink()  # the fixture already created it; start from nothing
    with TestClient(main.app) as client:
        assert client.get("/health").json()["status"] == "ok"
    assert isolated_settings.db_path.exists()
