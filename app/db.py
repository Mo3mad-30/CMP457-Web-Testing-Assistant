"""Storage: every scan, selection and model call, in SQLite (plan section 6.5).

Scans are append-only: a rescan is a new row, never an update. The full Inspection JSON stays in its
job folder; the database keeps an index of it plus everything the tester and the model produced.
Every function takes an optional db_path last, so tests can use a temporary database.
"""
import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import PROJECT_ROOT, settings
from shared.schemas import Inspection, ModelCallRecord, Selection

# ---------------------------------------------------------------------------
# Part 3.1: database setup
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspections (
    inspection_id   TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    final_url       TEXT NOT NULL,
    title           TEXT NOT NULL,
    scanned_at      TEXT NOT NULL,
    scope_selector  TEXT,
    screenshot_path TEXT,
    json_path       TEXT NOT NULL,
    element_count   INTEGER NOT NULL,
    warnings_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS elements (
    inspection_id    TEXT NOT NULL REFERENCES inspections(inspection_id),
    element_id       TEXT NOT NULL,
    tag              TEXT NOT NULL,
    role             TEXT,
    accessible_name  TEXT,
    best_locator     TEXT,
    best_match_count INTEGER,
    visible          INTEGER NOT NULL,
    enabled          INTEGER NOT NULL,
    PRIMARY KEY (inspection_id, element_id)
);

CREATE TABLE IF NOT EXISTS selections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_id    TEXT NOT NULL REFERENCES inspections(inspection_id),
    element_ids_json TEXT NOT NULL,
    goal             TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    inspection_id     TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    latency_ms        INTEGER NOT NULL,
    status            TEXT NOT NULL,
    is_fallback       INTEGER NOT NULL DEFAULT 0,
    fallback_reason   TEXT,
    created_at        TEXT NOT NULL,
    response_text     TEXT
);

-- Phase 2: versioned test cases, code and repairs. Empty in Phase 1.
CREATE TABLE IF NOT EXISTS artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    inspection_id TEXT REFERENCES inspections(inspection_id),
    version       INTEGER NOT NULL,
    content       TEXT NOT NULL,
    approved      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
"""

MODEL_CALL_COLUMNS = [
    "id", "created_at", "provider", "model", "purpose", "inspection_id", "prompt_tokens",
    "completion_tokens", "latency_ms", "status", "is_fallback", "fallback_reason",
]


def _db_file(db_path: Path | None) -> Path:
    return Path(db_path) if db_path is not None else settings.db_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _portable(path: Path | str) -> str:
    """Store paths relative to the project root when possible, so the database works on every laptop."""
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _absolute(stored: str) -> Path:
    p = Path(stored)
    return p if p.is_absolute() else PROJECT_ROOT / p


@contextmanager
def connect(db_path: Path | None = None):
    """Open the database, commit on success, roll back on error, always close."""
    path = _db_file(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Create any missing tables. Safe to call on every startup."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Part 3.2: scans
# ---------------------------------------------------------------------------

def save_inspection(inspection: Inspection, json_path: Path, db_path: Path | None = None) -> None:
    """Record a new scan and its elements. Refuses to overwrite: a rescan must use a new id."""
    with connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM inspections WHERE inspection_id = ?", (inspection.inspection_id,)
        ).fetchone()
        if exists:
            raise ValueError(f"inspection {inspection.inspection_id} already exists; scans are never overwritten")
        conn.execute(
            "INSERT INTO inspections (inspection_id, url, final_url, title, scanned_at, scope_selector,"
            " screenshot_path, json_path, element_count, warnings_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                inspection.inspection_id, inspection.url, inspection.final_url, inspection.title,
                inspection.scanned_at.isoformat(), inspection.scope_selector, inspection.screenshot_path,
                _portable(json_path), inspection.element_count, json.dumps(inspection.warnings), _now(),
            ),
        )
        conn.executemany(
            "INSERT INTO elements (inspection_id, element_id, tag, role, accessible_name,"
            " best_locator, best_match_count, visible, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    inspection.inspection_id, el.element_id, el.tag, el.role, el.accessible_name,
                    el.best_locator.value if el.best_locator else None,
                    el.best_locator.match_count if el.best_locator else None,
                    int(el.visible), int(el.enabled),
                )
                for el in inspection.elements
            ],
        )


def get_inspection(inspection_id: str, db_path: Path | None = None) -> Inspection | None:
    """The full scan, loaded from its JSON file. None if the id is unknown or the file is gone."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT json_path FROM inspections WHERE inspection_id = ?", (inspection_id,)
        ).fetchone()
    if row is None:
        return None
    path = _absolute(row["json_path"])
    if not path.exists():
        return None
    return Inspection.model_validate_json(path.read_text(encoding="utf-8"))


def list_inspections(db_path: Path | None = None) -> list[dict]:
    """All scans, newest first, for the History page."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT inspection_id, url, final_url, title, scanned_at, scope_selector, element_count"
            " FROM inspections ORDER BY scanned_at DESC, created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Part 3.3: selections
# ---------------------------------------------------------------------------

def save_selection(selection: Selection, db_path: Path | None = None) -> int:
    """Store the tester's chosen elements and goal. Returns the new row id."""
    try:
        with connect(db_path) as conn:
            cur = conn.execute(
                "INSERT INTO selections (inspection_id, element_ids_json, goal, created_at) VALUES (?, ?, ?, ?)",
                (selection.inspection_id, json.dumps(selection.element_ids), selection.goal,
                 selection.created_at.isoformat()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"unknown inspection {selection.inspection_id}") from exc


def get_latest_selection(inspection_id: str, db_path: Path | None = None) -> Selection | None:
    """The most recent selection for a scan, or None if the tester has not saved one yet."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT inspection_id, element_ids_json, goal, created_at FROM selections"
            " WHERE inspection_id = ? ORDER BY id DESC LIMIT 1",
            (inspection_id,),
        ).fetchone()
    if row is None:
        return None
    return Selection(
        inspection_id=row["inspection_id"],
        element_ids=json.loads(row["element_ids_json"]),
        goal=row["goal"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Part 3.4: model calls
# ---------------------------------------------------------------------------

def log_model_call(record: ModelCallRecord, response_text: str | None = None,
                   db_path: Path | None = None) -> int:
    """Store one model-call attempt (successful, failed or fallback). Returns the new row id."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO model_calls (provider, model, purpose, inspection_id, prompt_tokens,"
            " completion_tokens, latency_ms, status, is_fallback, fallback_reason, created_at, response_text)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.provider, record.model, record.purpose, record.inspection_id,
                record.prompt_tokens, record.completion_tokens, record.latency_ms, record.status,
                int(record.is_fallback), record.fallback_reason, record.created_at.isoformat(), response_text,
            ),
        )
        return cur.lastrowid


def list_model_calls(limit: int = 100, db_path: Path | None = None) -> list[dict]:
    """Most recent model calls first, for the usage page (response text left out)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(MODEL_CALL_COLUMNS)} FROM model_calls ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    calls = [dict(r) for r in rows]
    for c in calls:
        c["is_fallback"] = bool(c["is_fallback"])
    return calls


def export_model_calls_csv(path: Path, db_path: Path | None = None) -> Path:
    """Write every model call, oldest first, to a CSV file (usage evidence for the submission)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(MODEL_CALL_COLUMNS)} FROM model_calls ORDER BY id ASC"
        ).fetchall()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(MODEL_CALL_COLUMNS)
        writer.writerows([tuple(r) for r in rows])
    return path
