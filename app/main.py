"""FastAPI entry point. Run with:  uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup: make sure the folder for the database and job outputs exists."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Human-in-the-Loop Web Testing Assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Home page: URL input. Scan handling is added in the inspector task."""
    return templates.TemplateResponse(
        request, "index.html", {"model": f"{settings.model_provider} / {settings.model_name}"}
    )


@app.get("/health")
def health():
    """Quick check that the app runs and which model is configured (never returns keys)."""
    return {
        "status": "ok",
        "model_provider": settings.model_provider,
        "model_name": settings.model_name,
        "model_key_set": bool(settings.groq_api_key or settings.gemini_api_key),
    }

# Task 5 (Person B): findings display and human selection.
# Keep these routes separate from A's scan/storage routes and C's /ask route.
from datetime import datetime, timezone

from fastapi import Form, HTTPException
from shared.schemas import Inspection, Selection

# Temporary sample-only selection while A's storage task is unfinished.
# Real inspections always use A's db.get_latest_selection / db.save_selection.
_sample_selection: Selection | None = None


def _findings_inspection(inspection_id: str) -> Inspection:
    if inspection_id == "sample":
        return Inspection.model_validate_json(
            (BASE_DIR.parent / "docs" / "sample_inspection.json").read_text(encoding="utf-8")
        )
    from app import db
    inspection = db.get_inspection(inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return inspection


def _findings_selection(inspection_id: str) -> Selection | None:
    if inspection_id == "sample":
        return _sample_selection
    from app import db
    return db.get_latest_selection(inspection_id)


def _findings_context(inspection: Inspection, selection: Selection | None,
                      message: str | None = None, error: str | None = None) -> dict:
    # A owns the screenshot response endpoint. Only show the image when its file exists.
    screenshot_available = False
    if inspection.inspection_id != "insp-0001" and inspection.screenshot_path:
        screenshot_root = (settings.data_dir / "jobs" / inspection.inspection_id).resolve()
        screenshot_file = (BASE_DIR.parent / inspection.screenshot_path).resolve()
        screenshot_available = (
            screenshot_file == screenshot_root / "screenshot.png"
            and screenshot_file.is_file()
        )
    return {
        "inspection": inspection, "selection": selection, "ask": None,
        "message": message, "error": error,
        "model": f"{settings.model_provider} / {settings.model_name}",
        "screenshot_available": screenshot_available,
    }


@app.get("/inspections/{inspection_id}", response_class=HTMLResponse)
def show_findings(request: Request, inspection_id: str):
    inspection = _findings_inspection(inspection_id)
    return templates.TemplateResponse(request, "findings.html", _findings_context(
        inspection, _findings_selection(inspection_id)))


@app.post("/inspections/{inspection_id}/select", response_class=HTMLResponse)
def save_findings_selection(request: Request, inspection_id: str,
                            element_ids: list[str] = Form(default=[]), goal: str = Form(default="")):
    global _sample_selection
    inspection = _findings_inspection(inspection_id)
    current = _findings_selection(inspection_id)
    unique_ids = list(dict.fromkeys(element_ids))
    cleaned_goal = goal.strip()
    error = None
    if not unique_ids:
        error = "Select at least one element."
    elif any(inspection.get_element(element_id) is None for element_id in unique_ids):
        error = "Selection contains an element not found in this inspection."
    elif len(cleaned_goal.split()) < 3:
        error = "Write a testing goal of at least three words."
    if error:
        return templates.TemplateResponse(request, "findings.html", _findings_context(
            inspection, current, error=error), status_code=400)
    selection = Selection(inspection_id=inspection.inspection_id, element_ids=unique_ids,
                          goal=cleaned_goal, created_at=datetime.now(timezone.utc))
    if inspection_id == "sample":
        _sample_selection = selection
    else:
        from app import db
        try:
            db.save_selection(selection)
        except ValueError as exc:  # plan 6.5: unknown inspection
            return templates.TemplateResponse(request, "findings.html", _findings_context(
                inspection, current, error=f"Selection not saved: {exc}"), status_code=400)
    return templates.TemplateResponse(request, "findings.html", _findings_context(
        inspection, selection, message="Selection saved"))
