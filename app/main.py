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
