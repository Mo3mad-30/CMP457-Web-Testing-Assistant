"""FastAPI entry point. Run with:  uvicorn app.main:app --reload

Each person adds only their own routes here (plan section 6.6).
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, runner_client
from app.config import PROJECT_ROOT, settings

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup: create the data folder and any missing database tables."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield


app = FastAPI(title="Human-in-the-Loop Web Testing Assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def model_label() -> str:
    """"<provider> / <model>", shown in the page header (plan 6.8)."""
    return f"{settings.model_provider} / {settings.model_name}"


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Home page: the scan form."""
    return templates.TemplateResponse(request, "index.html", {"model": model_label(), "error": None})


@app.get("/health")
def health():
    """Quick check that the app runs and which model is configured (never returns keys)."""
    return {
        "status": "ok",
        "model_provider": settings.model_provider,
        "model_name": settings.model_name,
        "model_key_set": bool(settings.groq_api_key or settings.gemini_api_key),
    }


# ---------------------------------------------------------------------------
# Part 4.2: scan, history and screenshot routes (Person A)
# ---------------------------------------------------------------------------

@app.post("/scan")
def scan(request: Request, url: str = Form(...), scope: str = Form("")):
    """Run the inspector in its own process, then open the new scan's findings page."""
    try:
        inspection = runner_client.run_inspection(url, scope)
    except runner_client.RunnerError as exc:
        context = {"model": model_label(), "error": str(exc), "url": url, "scope": scope}
        return templates.TemplateResponse(request, "index.html", context, status_code=400)
    return RedirectResponse(f"/inspections/{inspection.inspection_id}", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    """Every scan ever made, newest first: shows that results are retained."""
    context = {"model": model_label(), "inspections": db.list_inspections()}
    return templates.TemplateResponse(request, "history.html", context)


@app.get("/inspections/{inspection_id}/screenshot")
def screenshot(inspection_id: str):
    """The scan's screenshot. Only files inside data/jobs/ are ever served."""
    inspection = db.get_inspection(inspection_id)
    if inspection is None or not inspection.screenshot_path:
        raise HTTPException(status_code=404, detail="screenshot not found")
    path = Path(inspection.screenshot_path)
    path = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
    jobs_dir = (settings.data_dir / "jobs").resolve()
    if jobs_dir not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(path, media_type="image/png")
