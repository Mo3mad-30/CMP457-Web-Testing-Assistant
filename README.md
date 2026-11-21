# Human-in-the-Loop Web Testing Assistant

A web assistant that helps a **human tester** inspect a web page and work with a language model on what
to test, without the model ever acting on guesses. GenAI for Software Testing, Fall 2026 course project.

**Phase 1 (this submission):**
- Scan a page in a **visible browser** and extract its interactive elements, labels, attributes and
  candidate locators. Every locator is **counted on the live page**, so uniqueness is measured, not assumed.
- Show the findings **linked to the source page**: page URL and scan time, a screenshot with a box per
  element, and a table with filters.
- Let the tester **select elements, refine the scope and state a testing goal** (the scope-and-goal
  approval gate).
- **Ask the model** for a summary and a next step, grounded only in the selected elements. Every answer
  is validated against the scan, and every model call is logged with its provider, tokens and response time.

The full design (architecture, data flow, approval gates, validation, resources, Phase 2 path) is in
**`docs/design_document.pdf`**.

---

## Requirements

- Python **3.10+** (developed and measured on Windows with Python 3.11)
- About 300 MB of disk space for Chromium (installed by Playwright)
- A free **Groq** API key (primary model). A free **Google AI Studio** key for Gemini is optional; it is
  the automatic fallback when Groq fails.
- Internet access for the model calls and for scanning public sites

## Setup

**Windows (PowerShell):**
```powershell
git clone https://github.com/Mo3mad-30/CMP457-Web-Testing-Assistant.git
cd CMP457-Web-Testing-Assistant
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

**macOS / Linux:**
```bash
git clone https://github.com/Mo3mad-30/CMP457-Web-Testing-Assistant.git
cd CMP457-Web-Testing-Assistant
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Then open `.env` and put in **your own** keys (each team member has their own `.env`; it is never committed):
```
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=...        # optional: fallback model
```

### Settings (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `MODEL_PROVIDER` / `MODEL_NAME` | `groq` / `openai/gpt-oss-120b` | Primary model |
| `FALLBACK_PROVIDER` / `FALLBACK_MODEL_NAME` | `gemini` / `gemini-3.5-flash` | Used only if the primary still fails after one retry; empty = no fallback |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | empty | Your own keys |
| `ALLOWED_HOSTS` | `www.saucedemo.com,the-internet.herokuapp.com` | Hosts the scanner may open; empty = only the host you scan |
| `HEADLESS` | `false` | `false` = visible browser (required for the demo) |
| `BROWSER_HOLD_SECONDS` | `3` | How long the browser stays open after a scan |
| `RUNNER_TIMEOUT` | `60` | Seconds allowed for loading a page |
| `DATA_DIR`, `DB_PATH` | `data`, `data/app.db` | Where scans and the database are stored (git-ignored) |

## Run

```bash
uvicorn app.main:app --reload
```
Open **http://127.0.0.1:8000**. `http://127.0.0.1:8000/health` shows the configured model and whether a
key is set (it never shows the key).

## Using it

1. **Scan:** enter a URL (for example `https://www.saucedemo.com`), optionally a CSS scope such as `#login`,
   and click **Scan**. A Chromium window opens, inspects the page, stays open a few seconds and closes.
2. **Findings:** the page shows the source URL and scan time, the screenshot with element boxes, and the
   element table (best locator, uniqueness badge, all candidates with their match counts). Click a row to
   highlight its box. Use the filters, or rescan with a different scope.
3. **Select and set a goal:** tick the elements, write a testing goal (at least three words) and click
   **Save selection**.
4. **Ask model:** the panel shows the summary, the cited elements (click to jump to the row), the suggested
   next action, any clarifying questions, and the evidence line: provider, model, tokens, response time,
   status. If Groq failed and Gemini answered, the panel says so.
5. **History** lists every scan; scans are never overwritten.

**Local test page:** `tests/fixtures/login.html` has deliberate edge cases (duplicate links, a button named
only by `aria-label`, disabled and hidden buttons). Get its address with:
```bash
python -c "from pathlib import Path; print(Path('tests/fixtures/login.html').resolve().as_uri())"
```
and paste the printed `file:///...` address into the scan form. (Only files from `tests/fixtures/` can be
scanned.) The built-in sample scan at `/inspections/sample` supports selection but not Ask.

**Inspector on its own** (the same process the app starts):
```bash
python -m runner.inspect_page --url https://www.saucedemo.com --out data/jobs/manual-1 --hold-seconds 3
```

## Tests

```bash
python -m pytest -q
```
Expected: **140 passed, 2 skipped**. The 2 skipped tests make real model calls and run only on request:
```powershell
$env:RUN_LIVE_TESTS = "1"; python -m pytest -q -s tests/test_model_client_live.py      # PowerShell
```
```bash
RUN_LIVE_TESTS=1 python -m pytest -q -s tests/test_model_client_live.py                # macOS / Linux
```

## Evidence (submission)

| File | What it is |
|---|---|
| `docs/saucedemo_inspection.json` + `docs/saucedemo_screenshot.png` | A real scan of saucedemo.com, taken during the demo |
| `docs/sample_inspection.json` | The handwritten sample the app shows at `/inspections/sample` (also used by the tests) |
| `docs/model_usage.csv` | Every model call: provider, model, purpose, tokens, latency, status, fallback flag |
| `docs/design_document.pdf` | The design document |
| Demo video | VIDEO_LINK_HERE |

To export the model-call log yourself:
```bash
python -c "from app import db; print(db.export_model_calls_csv('docs/model_usage.csv'))"
```

## Models and limits

- **Primary:** Groq free tier, `openai/gpt-oss-120b`. **Fallback:** Gemini `gemini-3.5-flash`, Google AI
  Studio free tier. **No paid APIs or subscriptions are used.**
- Providers are called directly over HTTP (`httpx`), temperature 0.2, JSON output.
- On a rate limit or error: wait (5 s after a rate limit, 1 s after an error), retry once, then the fallback.
  An answer that fails validation is retried once with the problems listed; it never triggers the fallback.
- Groq free tier: 30 requests/min, 1,000 requests/day, 8,000 tokens/min. One Ask uses about 1,000 tokens
  (reasoning tokens included), so about 7 Asks a minute.
- Token counts come from the provider's response, never estimated. Every call is fresh (no caching).
- No local GPU is needed.

## Security

- API keys live only in `.env`, which is git-ignored. They are sent only in request headers and never
  appear in logs, records or error messages.
- Scans run in a **separate process** with no API keys, its own job folder and a time limit. Only http(s)
  pages (and local pages from `tests/fixtures/`) can be scanned, and navigation to hosts outside
  `ALLOWED_HOSTS` is blocked.
- Page content and model output are treated as untrusted: both are HTML-escaped on screen, and page text is
  passed to the model inside data markers it cannot break out of.

## Project layout

```
app/        web app: routes (main.py), storage (db.py), runner client, model client, prompts,
            validation, assistant (Ask flow), templates, static files
runner/     separate browser process: inspect_page.py
shared/     data contract used by app and runner (schemas.py)
tests/      140 tests + fixtures/login.html (local test page)
docs/       evidence (sample and real scans, model usage log), design document
data/       runtime data: database, scan folders, screenshots (git-ignored)
plan.md     team plan: decisions, shared names, progress, change log
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Executable doesn't exist ... ms-playwright` | Run `playwright install chromium` (about 200 MB; retry on a stable connection if the download stops) |
| "… is not an allowed host" | Add the host to `ALLOWED_HOSTS` in `.env` and restart the app |
| Model panel says no model answered | Check `GROQ_API_KEY` in `.env` (and `/health`), then restart the app; `.env` is read at start-up |
| Port 8000 in use | Stop the other server, or run `uvicorn app.main:app --port 8001` |
| VS Code: "Import … could not be resolved" | `Ctrl+Shift+P` → **Python: Select Interpreter** → the project's `.venv` |
| PowerShell error after pasting several lines | Paste commands one line at a time |
| Inspector tests fail with "Unable to capture screenshot" | Close screen recorders and other Chromium-heavy apps, then run the tests again |