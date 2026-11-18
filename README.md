# Human-in-the-Loop Web Testing Assistant

A supervised assistant that inspects a web page, helps a tester design and generate Playwright tests,
runs them after approval, and repairs them when the page changes.
GenAI for Software Testing, Fall 2026 course project.

## Status
Phase 1 (architecture and guided inspection), in progress.

## Project layout
```
app/          FastAPI web app: routes, templates, config, (soon) storage + model client
runner/       Separate browser-runner process: page inspection, (Phase 2) test execution
shared/       Data models shared by app and runner (inspection schema)
data/         Runtime data: SQLite DB, job folders, screenshots (not committed)
docs/         Sample inspection output, model usage evidence
tests/        Our own tests
```

## Setup
Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # Windows: copy .env.example .env
# then put your Groq API key in .env
```

## Run
```bash
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000 (home page) or http://127.0.0.1:8000/health (config check).

## Model configuration
- Primary: Groq free tier, `openai/gpt-oss-120b`
- Backup: Gemini Flash, Google AI Studio free tier
- Switch with `MODEL_PROVIDER` / `MODEL_NAME` in `.env`. No paid APIs are used.

## Secrets
API keys live only in `.env`, which is git-ignored. Never commit it.
