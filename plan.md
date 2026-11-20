# Team plan: Human-in-the-Loop Web Testing Assistant

Course: Generative AI for Software Testing, Fall 2026 · Team of 3
Phase 1 (Architecture and guided inspection): due Week 9, 10 pts
Phase 2 (Complete supervised workflow): due Week 13, 20 pts

This is the team's overall plan: what we are building, what we decided, what is done, and what each
remaining task must achieve. Technical design details live in the design document, the **Google Doc**
"Human-in-the-Loop Web Testing Assistant — Design Document" (the main copy; the earlier Claude doc is
an old draft). Both are updated after every important decision or step.

---

## 1. What we are building

A web app that helps a **human tester** inspect a web page, design test cases, generate Playwright
tests, run approved tests, and repair them after the page changes. The tester approves every
consequential step; the assistant asks instead of guessing when evidence is missing. Extra autonomy
earns no marks; grounded, reviewable behavior does.

How it looks to the tester: our app runs at `127.0.0.1:8000` in their normal browser (the control
panel). When they click Scan, a **separate Chromium window** opens, loads the target site, gets
inspected, stays open a few seconds, and closes. Results appear back in our app's tab. Nothing is
drawn on top of the site under test.

Guiding principle: **deterministic components produce facts** (inspector, locator counts, storage,
runner, later the diff engine); **the model produces suggestions** (summaries, test cases, code,
repairs); every suggestion is checked against the facts before the tester sees it.

---

## 2. Phase 1 rubric and where each point comes from

| Component | Pts | What graders want | Built by |
|---|---|---|---|
| Architecture and system design | 4 | Component diagram, data flow (UI, model, storage, isolated runner), approval points, validation, how later phases use inspection results | Design doc + schema contract + app/runner split |
| Working page inspection | 3 | URL → visible browser → interactive elements, labels/attributes, candidate locators → structured findings linked to the source page | Tasks 1, 2, 4, 5 |
| Basic human interaction | 2 | Testing goal + element selection or scope refinement in the UI | Task 5 (+ `Selection` in the schema) |
| Feasibility evidence | 1 | A meaningful model call using inspection data; model/version, setup, tokens, response time recorded | Tasks 6, 7, 8 |

**Submission:** design doc · runnable code + setup + model config (no secrets) · short demo ·
sample inspection output · model usage/timing evidence.

---

## 3. Decisions

| # | Topic | Decision | Why |
|---|---|---|---|
| 1 | Language | Python everywhere: FastAPI, Playwright for Python, pytest | Team already used Playwright + pytest in labs |
| 2 | Runner isolation | Separate process launched per job (container option documented for Phase 2) | Brief allows "process or container"; fastest; visible browser is easy |
| 3 | Model | Groq free tier, `openai/gpt-oss-120b` primary; Gemini Flash (free tier) backup; no local models | Local 7B models too weak for code/JSON and need a GPU; Groq is fast and free |
| 3a | Model client transport | Providers called directly with **`httpx`** (Groq's OpenAI-compatible endpoint; Gemini's own API), not the OpenAI library. Fallback model id **`gemini-3.5-flash`** | Works, well tested, reports Gemini's thinking tokens; decided 2026-11-20 |
| 3b | Call routing | Main model + **automatic fallback**: Groq → retry once → Gemini with the same prompt; always shown in the UI and logged. Manual model switch in the UI **on hold** | Demo never breaks on a rate limit; one answer per call; transparent |
| 4 | Frontend | Jinja2 HTML templates + a little vanilla JS | No build step, fastest |
| 5 | Storage | SQLite + one folder per scan; scans never overwritten | Zero setup; brief requires retained results |
| 6 | Browser window | Runner's own headed Chromium, kept open a few seconds after the scan (configurable) | Visible browser required; clear in the demo |
| 7 | UI placement | Separate control-panel tab; no overlay, no extension | Keeps our app and the site under test apart |
| 8 | Practice targets | saucedemo.com, the-internet.herokuapp.com, plus our own local test page | Until the instructor's site arrives |
| 9 | Schema | One shared data contract (`shared/schemas.py`) for inspection, selection, model output and usage log; tests keep the sample in sync | Lets the three of us work in parallel |
| 10 | Grounding rule | A model answer must cite **at least one** element id, and every cited id must exist in the scan; otherwise it is rejected (if Task 7a's branch lacks this, add it during the 7b review) | An answer that cites nothing cannot be checked against the scan |
| 11 | Keys | Each team member keeps their **own `.env`** with their own keys (copied from `.env.example`, never committed). New settings are added to `.env.example` with an empty value | Separate free-tier limits per person; no shared secrets |
| 12 | Invalid output | A rejected answer adds **one extra `model_calls` row** with status `invalid_output` (same provider/model, rejected text, no tokens, latency 0); `ok` rows are never changed. The panel's evidence line shows the **last successful** attempt | Honest, append-only evidence; no double-counted tokens |
| 13 | Sample scan | Save selection works on the sample; **Ask is not offered** there ("Scan a page first"). The Ask route calls `summarize_selection` (plan 6.6) | Usage evidence only refers to real scans |
| 14 | No outside knowledge | The system prompt forbids values that are not in the page data (usernames, passwords, messages); validation can only check ids | The model used a site username it knew from elsewhere |
| 15 | Model call settings | Temperature 0.2; retry waits 5 s after a rate limit, 1 s after an error; only the file name is sent for local `file://` pages; unused `openai` package removed | Reproducible answers; no local paths in prompts |

Rejected and why: sending every call to both models, or a second model judging the first (double the
calls; deterministic validation already checks); local Ollama (weak, GPU-bound); React (build step,
slower).

Model limits to respect (Groq free tier, `gpt-oss-120b`, published): 30 requests/min, 1,000/day,
8,000 tokens/min, 200,000 tokens/day. ⇒ prompts carry only the selected elements, never the whole page.

---

## 4. Project structure

    app/        web app: routes, pages, config, storage, runner client, model client, prompts, validation
    runner/     separate browser process: page inspection (Phase 2: test execution)
    shared/     data contract used by both app and runner
    data/       runtime only (database, scan folders, screenshots), not committed
    docs/       sample inspection output, model usage evidence, demo script
    tests/      our tests + a local test page

Rules: `runner/` never imports from `app/`. API keys only in `.env` (git-ignored). Every scan is a new
record. Run `pytest` after every change.

---

## 5. Progress and team split

| Step | Status | Owner | Notes |
|---|---|---|---|
| Skeleton (folders, config, home page, health check, README) | Done | Mohammad | Runs; `/health` shows the configured model |
| Data contract (`shared/schemas.py`) | Done | Mohammad | Inspection, Element, Locator, Selection, ModelSuggestion, ModelCallRecord (with fallback fields) |
| Sample inspection (`docs/sample_inspection.json`) | Done | Mohammad | Handwritten saucedemo login; replaced by a real scan later |
| Schema tests | Done | Mohammad | 4 passing |
| Design doc first draft | Done | Mohammad | Google Doc is the main copy |
| Task 1: Local test page | Done | Mohammad | 10 visible interactive elements + 1 hidden |
| Task 2: Inspector | Done | Person A (Mohammad) | `runner/inspect_page.py` + 14 tests (18 total passing); manual saucedemo run still to confirm |
| Task 3: Storage | Done | Person A (Mohammad) | `app/db.py` + 11 tests (29 total passing); tables created at app startup |
| Task 4: Runner client + scan pages | Done | Person A (Mohammad) | `app/runner_client.py`, scan/history/screenshot routes, `index.html`, `history.html`; 48 tests passing |
| Task 5: Findings page | Done | Person B | Reviewed, 2 small integration fixes + 8 tests added; merged to `main` (PR #1) |
| Task 6: Model client with fallback | Fix round | Person C | Branch `task-6-model-client`: logic and 33 tests pass; uses `httpx` (decision pending); no live call verified yet (no key) |
| Task 7a: Prompt + validation | Fix round | Person C | Branch `task-7a-prompt-validation`: 19 tests pass; needs fixes `16bdfa7` (role/tag injection) and `00d405e` (no cited ids = error) |
| Task 7b: "Ask model" wiring | Fix round | Person C | Branch `task-7b-ask-model` reviewed: real Ask works (local page 609+541 tokens, 2.2 s; saucedemo 636+379, 1.6 s), live Groq→Gemini fallback works; 135 tests with fixes |
| Task 8: Evidence package + README | Later | | Assigned after Tasks 3–7 |
| Task 9: Final rubric review | Later | | Assigned after Task 8 |

### Who does what

| Person | Tasks | Files they own |
|---|---|---|
| A (Mohammad) | 2 Inspector (done), 3 Storage (done), 4 Runner client + scan pages (done) | `runner/inspect_page.py`, `app/db.py`, `app/runner_client.py`, `index.html`, `history.html`, A's routes |
| B | 5 Findings page (done) | `findings.html`, `_model_panel.html`, `app/static/app.js`, `app/static/app.css`, B's routes |
| C | 6 Model client, 7a Prompt + validation, 7b "Ask model" wiring | `app/model_client.py`, `app/prompts.py`, `app/validation.py`, `app/assistant.py`, C's route |

Shared file: `app/main.py`. Each person adds **only their own routes** (section 6.6).

### Dependencies

| Task | Needs first | Start now? |
|---|---|---|
| 3. Storage | Schema (done) | Done |
| 4. Runner client + scan pages | Tasks 2 + 3 | Done |
| 5. Findings page | Task 4 | Done |
| 6. Model client | Task 3's `log_model_call` (done; still faked in unit tests) | Yes |
| 7a. Prompt + validation | Schema + sample | Yes |
| 7b. "Ask model" wiring | Tasks 3, 5, 6 | Last |

**Start right away:** Tasks 6 and 7a. Tasks 1–5 are done and merged into `main` (59 tests passing).
**Critical path:** 6 → 7b (the "Ask model" step). Then Tasks 8–9.

---

## 6. Shared names (use these exactly)

Everything below is used by more than one person. Use these names from day one, even before the code
behind them exists; a stub with the right name and signature is better than waiting. Changing anything
here needs agreement from all three of us and an update to this section.

### 6.1 Files and folders

| Path | Owner | Purpose |
|---|---|---|
| `shared/schemas.py` | all (agree first) | Data contract (6.3) |
| `docs/sample_inspection.json` | all | Sample `Inspection`; what B and C build against now |
| `tests/fixtures/login.html` | A | Local test page |
| `runner/inspect_page.py` | A | Inspector process (6.4) |
| `app/config.py` | all (agree first) | Settings (6.2) |
| `app/db.py` | A | Storage (6.5) |
| `app/runner_client.py` | A | Starts the runner, saves results (6.5) |
| `app/main.py` | shared | Routes (6.6) |
| `app/model_client.py` | C | Model calls + fallback (6.7) |
| `app/prompts.py` | C | Prompt building (6.7) |
| `app/validation.py` | C | Checks model output (6.7) |
| `app/assistant.py` | C | Ties prompt, model and validation together (6.7) |
| `app/templates/index.html`, `history.html` | A | Scan form, scan list |
| `app/templates/findings.html`, `_model_panel.html` | B | Findings page, model panel (6.8) |
| `app/static/app.js`, `app.css` | B | Page behavior and style |
| `data/app.db` | runtime | SQLite database |
| `data/jobs/<inspection_id>/inspection.json` | runtime | Scan result |
| `data/jobs/<inspection_id>/screenshot.png` | runtime | Full-page screenshot |
| `data/jobs/<inspection_id>/error.json` | runtime | Written instead of `inspection.json` when a scan fails: `{"error": "<message>"}` |

### 6.2 Settings (`app/config.py` → `settings.<name>`, `.env` key in brackets)

| Setting | `.env` key | Default |
|---|---|---|
| `model_provider` | `MODEL_PROVIDER` | `groq` |
| `model_name` | `MODEL_NAME` | `openai/gpt-oss-120b` |
| `fallback_provider` | `FALLBACK_PROVIDER` | `""` (no fallback) |
| `fallback_model_name` | `FALLBACK_MODEL_NAME` | `""` |
| `groq_api_key` | `GROQ_API_KEY` | `""` |
| `gemini_api_key` | `GEMINI_API_KEY` | `""` |
| `allowed_hosts` | `ALLOWED_HOSTS` (comma-separated) | `[]` = host of the scanned URL only |
| `runner_timeout` | `RUNNER_TIMEOUT` (seconds) | `60` |
| `headless` | `HEADLESS` | `false` |
| `browser_hold_seconds` | `BROWSER_HOLD_SECONDS` | `3` |
| `data_dir` | `DATA_DIR` | `data` |
| `db_path` | `DB_PATH` | `data/app.db` |

Provider names are exactly `groq` and `gemini`.

### 6.3 Data contract (`shared/schemas.py`)

Classes: `Locator`, `BoundingBox`, `Element`, `Inspection`, `Selection`, `ModelSuggestion`,
`ModelCallRecord`. Field names are as defined in the file; key ones:

- `Inspection`: `inspection_id`, `url`, `final_url`, `title`, `scanned_at`, `viewport`,
  `scope_selector`, `screenshot_path`, `elements`, `warnings`, `element_count` (computed),
  `get_element(element_id)`
- `Element`: `element_id`, `tag`, `role`, `accessible_name`, `text`, `label`, `attributes`,
  `css_path`, `visible`, `enabled`, `bounding_box`, `locators`, `best_locator` (computed)
- `Locator`: `strategy`, `value`, `match_count`, `is_unique` (computed)
- `Selection`: `inspection_id`, `element_ids`, `goal`, `created_at`
- `ModelSuggestion`: `summary`, `referenced_element_ids`, `suggested_next_action`, `clarifying_questions`
- `ModelCallRecord`: `provider`, `model`, `purpose`, `inspection_id`, `prompt_tokens`,
  `completion_tokens`, `latency_ms`, `status`, `is_fallback`, `fallback_reason`, `created_at`

Fixed values:
- Locator `strategy`: `role`, `label`, `placeholder`, `test_id`, `text`, `id`, `css` (ranked in this order)
- `ModelCallRecord.status`: `ok`, `invalid_output`, `rate_limited`, `error`
- `ModelCallRecord.purpose` (Phase 1): `summarize_selection`
- `fallback_reason` format: `"<provider> <status> after retry"`, e.g. `"groq rate_limited after retry"`

### 6.4 IDs and formats

| Thing | Format | Example |
|---|---|---|
| Inspection id | `insp-YYYYMMDD-HHMMSS-xxxx` (4 hex) | `insp-20261119-141502-a3f9` |
| Element id | `el-` + 3 digits, in page order | `el-001` |
| Timestamps | UTC, ISO 8601 | `2026-11-19T12:15:02Z` |
| Locator `value` | A Playwright Python call on `page`, ready to paste into Phase 2 code | `get_by_role("button", name="Log in", exact=True)` |
| Screenshot path in JSON | Relative to the project root | `data/jobs/insp-…/screenshot.png` |

**Inspector command line (A's runner, called by A's runner client):**
`python -m runner.inspect_page --url URL --out DIR [--inspection-id ID] [--scope CSS] [--allowed-hosts h1,h2] [--timeout SECONDS] [--hold-seconds N] [--headless] [--include-hidden]`
Exit codes: `0` success (`inspection.json` written), `1` failure (`error.json` written),
`2` host not allowed (`error.json` written).

### 6.5 Storage and runner client functions (A)

All `db` functions take an optional `db_path` as the last argument (tests use a temp file).

| Function | Returns | Used by |
|---|---|---|
| `db.init_db()` | None | `main.py` at startup |
| `db.save_inspection(inspection: Inspection, json_path: Path)` | None; raises `ValueError` if the id already exists | runner client |
| `db.get_inspection(inspection_id: str)` | `Inspection` or `None` (unknown id, or its JSON file is missing) | B, C |
| `db.list_inspections()` | `list[dict]`, newest first, keys: `inspection_id`, `url`, `final_url`, `title`, `scanned_at`, `scope_selector`, `element_count` | A (history page) |
| `db.save_selection(selection: Selection)` | `int` (row id); raises `ValueError` for an unknown inspection | B |
| `db.get_latest_selection(inspection_id: str)` | `Selection` or `None` | B, C |
| `db.log_model_call(record: ModelCallRecord, response_text: str | None = None)` | `int` (row id) | C |
| `db.list_model_calls(limit: int = 100)` | `list[dict]`, newest first, columns in `db.MODEL_CALL_COLUMNS`, `is_fallback` as bool, no response text | usage page (later) |
| `db.export_model_calls_csv(path: Path)` | `Path`; all calls, oldest first, header = `db.MODEL_CALL_COLUMNS` | evidence (later) |
| `runner_client.RunnerError` | exception class | A's `/scan` route |
| `runner_client.new_inspection_id()` | `str` | runner client |
| `runner_client.run_inspection(url: str, scope: str | None = None)` | `Inspection` (already saved); raises `RunnerError` with a one-line message | A's `/scan` route |
| `runner_client.validate_url(url: str)` | None; raises `RunnerError` (only http(s), or files in `tests/fixtures/`) | runner client |
| `tests/conftest.py` → `isolated_settings` fixture | Temporary data folder + database, headless runner, no hold | everyone's tests |

Table names: `inspections`, `elements`, `selections`, `model_calls`, `artifacts` (Phase 2, empty).

**Storage is done (Task 3).** Until scans come from the UI (Task 4), B still loads the sample with
`Inspection.model_validate_json(Path("docs/sample_inspection.json").read_text())` when the id is
`sample`. C can log real calls with `db.log_model_call`, and replaces it with a fake in unit tests
(pytest `monkeypatch`). Tests pass a temporary `db_path` so they never touch `data/app.db`.

### 6.6 Routes (`app/main.py`)

| Method + path | Form fields | Renders / does | Owner |
|---|---|---|---|
| `GET /` | | `index.html` (scan form with scope, last error) | A |
| `GET /health` | | JSON config check | exists |
| `POST /scan` | `url`, `scope` (optional) | Runs the inspector → redirect `303` to `/inspections/{inspection_id}`; on `RunnerError` re-renders `index.html` with `error` | A |
| `GET /history` | | `history.html` (all scans) | A |
| `GET /inspections/{inspection_id}/screenshot` | | Screenshot file (only from `data/jobs/`) | A |
| `GET /inspections/{inspection_id}` | | `findings.html`; `sample` loads the sample JSON; unknown id → 404 (JSON) | B |
| `POST /inspections/{inspection_id}/select` | `element_ids` (repeated), `goal` | Saves a `Selection` → re-renders `findings.html` with `message` | B |
| `POST /inspections/{inspection_id}/ask` | (none) | Runs `assistant.summarize_selection` → re-renders `findings.html` with `ask`. Build the context with B's `_findings_context(inspection, selection)` helper in `app/main.py`, then set `ctx["ask"] = ask` (the helper always sets `ask = None`) | C |

Rescan = a form on the findings page posting to `POST /scan` with the same `url` and a new `scope`.

### 6.7 Model, prompt and validation functions (C)

| Function / class | Signature / fields | Used by |
|---|---|---|
| `model_client.ModelResult` | `text: str | None`, `provider: str`, `model: str`, `is_fallback: bool`, `fallback_reason: str | None`, `attempts: list[ModelCallRecord]` | C, B (panel) |
| `model_client.call_model` | `(messages: list[dict], purpose: str, inspection_id: str | None = None, json_mode: bool = True) -> ModelResult` | C |
| `prompts.PAGE_DATA_OPEN` / `PAGE_DATA_CLOSE` | `"<page_data>"` / `"</page_data>"` | C (tests) |
| `prompts.compact_element` | `(element: Element) -> dict` | C |
| `prompts.build_summary_messages` | `(inspection: Inspection, selection: Selection) -> list[dict]` | C |
| `validation.ValidationResult` | `suggestion: ModelSuggestion | None`, `errors: list[str]`, `warnings: list[str]` | C |
| `validation.validate_suggestion` | `(raw_text: str, inspection: Inspection, selection: Selection) -> ValidationResult` | C |
| `assistant.AskResult` | `suggestion: ModelSuggestion | None`, `errors: list[str]`, `warnings: list[str]`, `result: ModelResult | None` | C, B (panel) |
| `assistant.summarize_selection` | `(inspection_id: str) -> AskResult` | C's `/ask` route |

### 6.8 Template variables

`findings.html` always receives:

| Variable | Type | Meaning |
|---|---|---|
| `inspection` | `Inspection` | The scan being shown |
| `selection` | `Selection` or `None` | Latest saved selection for this scan |
| `ask` | `AskResult` or `None` | Model answer, only after "Ask model" |
| `message` | `str` or `None` | Success note, e.g. "Selection saved" |
| `error` | `str` or `None` | Error note shown at the top |
| `model` | `str` | `"<provider> / <model>"` label used by `base.html` |

`findings.html` also receives `screenshot_available` (bool). `_model_panel.html` is included by
`findings.html` and reads only `ask`; it shows a placeholder when `ask` is `None`. The panel shows tokens,
latency and status from the **last** entry in `result.attempts`, lists every non-`ok` attempt as a
collapsed "failed attempts" list, uses `is_fallback` / `fallback_reason` for the fallback note, and
turns `referenced_element_ids` into buttons that jump to the table row. The Ask button is a form posting
to `POST /inspections/{id}/ask` with no fields, disabled until a selection is saved.

`index.html`: `model`, `error`, and on a failed scan also `url`, `scope` (so the form keeps the tester's input). `history.html`: `model`, `inspections` (from `db.list_inspections()`). `base.html` has the header with Scan and History links and the model label; pages add their own CSS or scripts in the `head` block.

---

## 7. Remaining tasks

### Task 2: Inspector, Person A (Working page inspection, 3 pts) (Done)
**Target:** a standalone process that opens a **visible** browser, reads the page, and writes one
inspection file that matches the data contract.
**Must do:**
- Accept the command-line options in 6.4.
- Refuse hosts outside the allowlist; block navigation away from allowed hosts while the page loads.
- Collect interactive elements (links, buttons, inputs, selects, textareas, elements with button/link
  roles), each with tag, visible text, label, key attributes, role, accessible name, visible/enabled
  state, position on the screenshot, and a short CSS path.
- Generate locator candidates in the ranked order (6.3). **Count every candidate on the live page**;
  drop ones that match nothing, keep non-unique ones as evidence.
- Skip hidden elements by default (with a warning), warn about iframes, take a full-page screenshot,
  keep the browser open for the hold time, then close.
- On failure, write `error.json` and exit with the codes in 6.4.
**Done when:** tests against the local test page pass (labels found, duplicate links non-unique,
disabled and hidden handled, scope works, 10 visible elements + 1 hidden warning), and a manual
saucedemo scan opens a visible browser and writes a valid file.
**Result:** built in seven parts (command line and host checks; page loading with navigation allowlist; in-browser element collection; role and accessible name; ranked locator candidates counted on the live page; building the Inspection, screenshot, hold time and exit codes; tests). On the test page it finds exactly 10 visible elements, the hidden one as a warning, both "Help" links as non-unique (count 2, best locator falls back to `#id`), no role for the password field and the disabled button as `enabled: false`. Extra warnings it can report: blocked navigations, page never went network-idle, HTTP error status, scope matched nothing, iframes not inspected.

### Task 3: Storage, Person A (Done)
**Target:** keep every scan, selection and model call, so later steps use what was really observed
and usage can be exported as evidence.
**Must do:** the functions and tables in 6.5; saving the same scan twice is refused; every model-call
attempt is stored, including fallbacks. **Push stubs with the 6.5 names first** so B and C can import them.
**Done when:** the sample scan round-trips through the database, selections save and load, and a test
CSV export works.
**Result:** built in six parts (database setup and tables; scans with append-only enforced; selections; model-call log and CSV export; table creation at app startup; tests). Paths are stored relative to the project root so the database works on every laptop; foreign keys stop selections for unknown scans; the `elements` table is a quick index while the full data stays in each scan's JSON file.

### Task 4: Runner client + scan pages, Person A (Done)
**Target:** connect the app to the inspector through the process boundary, with a time limit and
**no API keys** passed to the runner.
**Must do:** `run_inspection` (6.5) starts the runner with a minimal environment and a timeout, then
saves the result; the routes `POST /scan`, `GET /history`, screenshot route (6.6); the scan form shows
"a browser window will open"; a clear error when the runner fails or times out.
**Done when:** scanning saucedemo from the UI opens the visible browser, then shows the findings page;
a second scan creates a new record and keeps the old one.
**Result:** built in four parts (runner client; scan, history and screenshot routes; scan form and history pages with navigation; tests). The runner client accepts only http(s) URLs and local test pages from `tests/fixtures/`, passes the runner only a short list of safe environment variables (never API keys), stops it after page-load limit + hold time + 15 s, and turns failures into one-line messages on the scan form (a blocked host says to add it to `ALLOWED_HOSTS`). The screenshot route serves files only from `data/jobs/`. Tests share a `tests/conftest.py` fixture (`isolated_settings`) that gives each test its own data folder and database. After a scan the app redirects to `/inspections/{id}`, which is Person B's findings page (404 until Task 5 lands).

### Task 5: Findings page, Person B (Basic human interaction, 2 pts) (Done)
**Target:** show the findings linked to their source page and let the tester select elements, refine
the scope and state a goal.
**Start with:** `GET /inspections/sample` rendering the sample JSON (6.5, 6.6). The sample has no
screenshot file, so the page must handle a missing screenshot.
**Must do:**
- Header: source URL, title, scan time, element count, scope used, warnings, Rescan and History links.
- Screenshot with a box per element; clicking a table row highlights its box and the other way round.
- Table: checkbox, element id, tag/role, name, label, key attributes, best locator, uniqueness badge
  (red when there is no unique locator: "assistant will ask"), visible/enabled, all candidates expandable.
- Filters: by type, text search, hide links, only unique. Rescan with a CSS scope.
- Goal box + "Save selection" (at least one element and a goal of a few words), then "Ask model".
- `_model_panel.html` layout from the `AskResult` fields (6.7): summary, referenced elements
  (clickable), next action, clarifying questions, evidence line (provider, model, tokens, latency,
  status), a visible note when the fallback answered, failed attempts collapsed underneath.
  Until C's code lands, test the panel with a hand-made `AskResult`.
- On hold: a manual model dropdown.
**Done when:** on the sample (and later on real scans) a tester can filter, select 2–3 elements,
write a goal and save it; the panel renders a test `AskResult`.

**Result:** reviewed against this plan and merged into `main` (PR #2 for Tasks 2–4, then PR #1 for
Task 5; 59 tests passing on `main`; real end-to-end run passed: local test page, filters, row/box
highlighting, selection save and refusals, rescan with scope, saucedemo, blocked host, sample page).
Integration fixes: CSS/JS moved into `base.html`'s `head` block; `/select` turns a storage `ValueError`
into a 400 message. Added `tests/test_findings_routes.py` (8 tests, incl. HTML escaping of scanned text).
Additions beyond the plan: viewport in the header; one "Assistant will ask" badge; browser-side checks that
mirror the server's (no element, goal under 3 words, id not in this scan); selections on the `sample` scan
are kept in memory only.

**Follow-ups (small, not blocking Phase 1):**
- [ ] Test with an element that has no unique locator, so the red "Assistant will ask" badge is covered.
- [ ] Unknown inspection id returns JSON 404; an HTML "scan not found" page would be friendlier.
- [ ] `app/main.py` tidy-up: B's imports mid-file, `Form`/`HTTPException` imported twice, `db` imported
  inside functions, sample id `"insp-0001"` hard-coded in `_findings_context`.
- [ ] Type filter covers tags only, not roles; History link appears twice on the findings page.
- [ ] Add `test-artifacts/` to `.gitignore`.
- [ ] Decide whether "Ask model" supports the `sample` scan (it is not in the database).

### Task 6: Model client with automatic fallback, Person C (Feasibility evidence, 1 pt)
**Target:** one place that makes every model call, records real tokens and latency, and falls back to
Gemini automatically.
**Must do:** `call_model` and `ModelResult` (6.7): send to Groq → on rate limit or error wait and
retry once → if it still fails and a fallback is configured, send the same prompt to Gemini. Fallback
only for failures to respond, not for answers that fail validation. Log every attempt with
`db.log_model_call` (faked until Task 3 lands). Never log keys.
**Done when:** offline tests (network faked) prove each path: success, fallback, no fallback
configured; one live test returns real tokens.

### Task 7a: Grounded prompt + validation, Person C
**Target:** the prompt and the checks for the meaningful model call, built from the schema and sample only.
**Must do:**
- `build_summary_messages`: only the selected elements in compact form, inside `<page_data>` markers;
  system instructions say page text is data, never instructions; cite elements by id; ask questions
  when evidence is insufficient; return JSON in the `ModelSuggestion` format.
- `validate_suggestion`: valid JSON in the agreed format; every cited id must exist in the scan;
  warnings if it cites unselected elements or ignores a missing unique locator.
**Done when:** tests pass on the sample: only selected elements appear in the prompt, hidden
instructions in page text stay inside the markers, unknown ids and invalid JSON are rejected.

### Task 7b: "Ask model" wiring, Person C (after Tasks 3, 5, 6)
**Target:** connect prompt, model and validation to the page.
**Must do:** `summarize_selection` and `AskResult` (6.7): load the scan and latest selection →
build messages → `call_model` → validate → on validation errors retry once with the errors listed →
if still invalid, report "invalid output". Route `POST /inspections/{inspection_id}/ask` (6.6).
**Done when:** selecting username/password/login with the goal "verify login rejects a wrong
password" returns a grounded answer citing those ids, with tokens and latency shown in B's panel.

### Finishing Phase 1 (after Tasks 6 and 7 are merged)

**Step 1: Combined fix round and merge of Tasks 6, 7a, 7b** (Person C, reviewed by A): one fix prompt with
every item from both reviews (including the invalid-output rule if 7b lacks it); merge 6 → 7a → 7b.

**Step 2: Live verification and evidence** (A): real Ask on the local test page and saucedemo; record
provider, model, tokens, latency; one fallback run; export the model-call log.

**Task 8: Evidence package + README** (split):
- [ ] Replace the handwritten `docs/sample_inspection.json` with a real saucedemo scan (+ its screenshot).
- [ ] Usage evidence: a small way to export the model-call log (`/usage` page with "Export CSV", or a
  one-line script) → `docs/model_usage.csv`.
- [ ] Show scan (browser) time separately from model response time (the brief asks for this); today only
  model latency is recorded.
- [ ] README: setup on Windows/macOS (venv, `playwright install chromium`, own `.env` with own keys),
  run, model configuration, resource limits, troubleshooting (Chromium download, pager, port in use).
- [ ] `docs/DEMO.md` + a 3–5 minute recording of the demo script (section 8).
- [ ] Optional: a ready-made CSS file linked in `base.html` for a cleaner demo.

**Design doc gaps to close:**
- [ ] "Ask model" flow (from the 7b review): retry on validation failure, invalid-output recording, what
  the tester sees in each outcome.
- [ ] Real measured tokens and latency (local page and saucedemo) and the hardware/OS/Python used.
- [ ] A "Testing and evidence" section: test count and what the tests cover, the end-to-end run, where the
  sample output and usage CSV are; remove the old test count from the findings section.
- [ ] A short "How Phase 2 uses Phase 1 results" table (snapshot → test design, locators → code
  generation, stored scans → rescan diff, selections → approved scope, call log → usage dashboard).
- [ ] A data-flow diagram with the approval gates marked (the flow is only a list today).
- [ ] Say that every model call is fresh in Phase 1 (no cached answers), and that scan time and model time
  are shown separately.
- [ ] Note that observations and business-rule assumptions are kept apart (the model asks when expected
  behavior was not observed).
- [ ] Limitations: approximate accessible names, single-user local app, sample-scan selections in memory.
- [ ] Final read-through for length ("short design document") and export to PDF for submission.

**Task 9: Final review and submission** (all):
- [ ] Rubric check: every row has evidence (screen, file, doc section).
- [ ] Clean-machine check: clone, follow the README, run the demo.
- [ ] Secrets check: no `.env`, keys or `data/` in the repo or the submission.
- [ ] Code-discussion prep: each person can explain every task, not only their own.
- [ ] Package: repo link or zip, design doc PDF, demo video, sample inspection, usage CSV.
- [ ] Follow-ups from the Task 5 review (small fixes) and the open "Ask on the sample scan" decision.

### Done
- **Task 1: Local test page** (`tests/fixtures/login.html`): login form with labeled fields,
  checkbox, dropdown, test-id button; duplicate "Help" links; `aria-label`-only button; disabled and
  hidden buttons; result area with real success/error messages (valid login tester / secret).
  Expected inspector result: 10 visible interactive elements + 1 hidden button warning.

---

## 8. Demo script (draft)

1. Open our app, enter the supplied URL, click Scan; the visible browser opens and closes.
2. Findings page: source URL and scan time, screenshot with boxes, table with locators and uniqueness.
3. Filter the table; rescan with a scope.
4. Select elements, write a goal, save.
5. Ask the model; show the grounded answer, cited elements, tokens and latency.
6. History page: earlier scans are kept.

---

## 9. Open questions

- Phase 1 exact deadline date (Week 9).
- Names for Person B and Person C.

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-11-17 | Stack decisions: Python everywhere, runner as separate process, Groq + Gemini, frontend deferred |
| 2026-11-18 | Skeleton built; design doc first draft; frontend = Jinja2; browser stays open a few seconds after scans |
| 2026-11-18 | Data contract, sample inspection and schema tests added; password field has no ARIA role (sample fixed) |
| 2026-11-18 | Call routing: main model + automatic fallback (option C); manual switch (option D) on hold |
| 2026-11-18 | plan.md rewritten as the team plan (no code); kept in sync with the design doc after every decision or step |
| 2026-11-18 | Task 1 done: local test page with deliberate edge cases and real login behavior; a modified copy is planned for Phase 2 rescan tests |
| 2026-11-18 | Design doc moved to Google Docs as the main copy; the Claude doc is no longer updated |
| 2026-11-18 | Google Doc synced: fallback settings in the model table, runner blocks only navigations to other hosts, browser hold time, fallback fields in the storage table |
| 2026-11-19 | Task dependencies mapped; Task 7 split into 7a (prompt + validation) and 7b (wiring); three-person split in three stages |
| 2026-11-19 | Owners set: A = Tasks 2–4, B = Task 5, C = Tasks 6–7; Tasks 8–9 deferred; added section 6, Shared names (files, settings, IDs, functions, routes, template variables) |
| 2026-11-19 | Design doc: added why the runner is a separate process (untrusted pages and generated code, failure containment, brief requirement, one job interface) and why a process rather than a container in Phase 1 |
| 2026-11-19 | Task 2 done: inspector with measured locators, exact-match names, navigation allowlist, warnings and exit codes; 18 tests passing; design doc inspection section updated |
| 2026-11-19 | Task 3 done: SQLite storage (append-only scans, selections, every model-call attempt, CSV export), tables created at startup; 29 tests passing; design doc storage section updated |
| 2026-11-19 | Fix: added httpx to requirements.txt (needed by FastAPI TestClient in test_db.py) |
| 2026-11-20 | Task 4 done: runner client (URL rules, minimal environment, time limit, one-line errors), scan/history/screenshot routes and pages; Person A's tasks complete; 48 tests passing; design doc runner section updated |
| 2026-11-20 | Task 5 reviewed and merged: PR #2 (Tasks 2–4) then PR #1 (Task 5) into `main`; 2 integration fixes, 8 findings-page tests added; 59 tests passing; real end-to-end run passed; design doc gained a "Findings page and tester interaction" section and an updated scope-and-goal gate |
| 2026-11-20 | Tasks 6 and 7a reviewed (not merged): both pass with `main` (112 tests with fixes); injection fix and empty-citation fix proposed; open decisions: httpx vs OpenAI library, how `invalid_output` is recorded, failure-reason message, Gemini model id; live call still to verify |
| 2026-11-20 | Decisions: httpx accepted for the model client; fallback model gemini-3.5-flash; at least one cited element required for grounding; one .env per person. Deferred to the 7b review: failure-reason message, temperature/retry waits/cleanup, how invalid_output is recorded |
| 2026-11-20 | Agreed (on hold until the 7b review): record a failed validation as one extra `model_calls` row with status `invalid_output` (same provider/model, rejected answer as response text, no tokens, latency 0); apply in the combined fix round only if 7b does not already handle it |
| 2026-11-20 | Phase 1 finishing list added (fix round, live evidence, Task 8 split, design-doc gaps, Task 9 checklist); design doc data-flow step 1 corrected (goal is set on the findings page, not with the URL) |
| 2026-11-21 | Task 7b reviewed. Decisions 12–15 (invalid-output row, no Ask on the sample scan, no outside knowledge, model call settings). One combined fix round for Tasks 6, 7a, 7b prepared (fixes from both reviews + sample form fix + panel evidence line); merge after confirmation. Design doc gained an "Asking the model" section with measured tokens and latency |