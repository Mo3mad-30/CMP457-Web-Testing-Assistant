"""Runner client: starts the inspector as a separate process and saves what it returns (plan 6.5).

The app never drives a browser itself. It sends a job (command-line options) to
`python -m runner.inspect_page`, waits with a time limit, and reads the files the runner writes.
The runner gets a minimal environment: no API keys or other secrets.
"""
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from app import db
from app.config import PROJECT_ROOT, settings
from shared.schemas import Inspection

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

# Only what Python, Playwright and the browser need to start. Nothing else is passed on.
SAFE_ENV_VARS = [
    # all systems
    "PATH", "HOME", "LANG", "TEMP", "TMP", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH",
    # Windows
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "COMSPEC", "PATHEXT",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    # Linux desktops (needed for a visible browser window)
    "DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
]


class RunnerError(Exception):
    """A scan could not be completed. The message is shown to the tester as-is."""


# ---------------------------------------------------------------------------
# Part 4.1: runner client
# ---------------------------------------------------------------------------

def new_inspection_id() -> str:
    """insp-YYYYMMDD-HHMMSS-xxxx (UTC time + 4 random hex characters, so two scans never collide)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"insp-{stamp}-{secrets.token_hex(2)}"


def minimal_env() -> dict[str, str]:
    """The environment the runner starts with: only the safe variables that exist on this machine."""
    return {name: os.environ[name] for name in SAFE_ENV_VARS if name in os.environ}


def validate_url(url: str) -> None:
    """Accept http(s) pages, and local files only from our test-page folder."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if not parsed.hostname:
            raise RunnerError(f"not a valid page address: {url}")
        return
    if parsed.scheme == "file":
        local = Path(unquote(parsed.path.lstrip("/") if os.name == "nt" else parsed.path)).resolve()
        if FIXTURES_DIR.resolve() in local.parents:
            return
        raise RunnerError("local files can only be scanned from tests/fixtures/")
    raise RunnerError(f"only http and https pages can be scanned (got '{parsed.scheme or url}')")


def allowed_hosts_for(url: str) -> list[str]:
    """The allowlist sent to the runner: ALLOWED_HOSTS from .env, or else only the scanned host."""
    host = urlparse(url).hostname
    return list(settings.allowed_hosts) or ([host] if host else [])


def build_command(url: str, job_dir: Path, inspection_id: str, scope: str | None) -> list[str]:
    """The exact command line for the runner (plan 6.4)."""
    cmd = [
        sys.executable, "-m", "runner.inspect_page",
        "--url", url,
        "--out", str(job_dir),
        "--inspection-id", inspection_id,
        "--allowed-hosts", ",".join(allowed_hosts_for(url)),
        "--timeout", str(settings.runner_timeout),
        "--hold-seconds", str(settings.browser_hold_seconds),
    ]
    if settings.headless:
        cmd.append("--headless")
    if scope:
        cmd += ["--scope", scope]
    return cmd


def read_error(job_dir: Path, result: subprocess.CompletedProcess) -> str:
    """The runner's own error message, or the end of its stderr if it crashed before writing one."""
    error_file = job_dir / "error.json"
    if error_file.exists():
        try:
            message = json.loads(error_file.read_text(encoding="utf-8"))["error"]
            return message.strip().splitlines()[0]  # first line only; the rest is Playwright's call log
        except (ValueError, KeyError, IndexError):
            pass
    tail = (result.stderr or "").strip().splitlines()[-3:]
    return " ".join(tail) or f"runner exited with code {result.returncode}"


def run_inspection(url: str, scope: str | None = None) -> Inspection:
    """Scan one page in a separate process, save the result, return it. Raises RunnerError."""
    url = url.strip()
    scope = (scope or "").strip() or None
    validate_url(url)

    inspection_id = new_inspection_id()
    job_dir = settings.data_dir / "jobs" / inspection_id
    job_dir.mkdir(parents=True, exist_ok=True)
    limit = settings.runner_timeout + settings.browser_hold_seconds + 15  # load + hold + browser start-up

    try:
        result = subprocess.run(
            build_command(url, job_dir, inspection_id, scope),
            cwd=PROJECT_ROOT, env=minimal_env(), capture_output=True, text=True, timeout=limit,
        )
    except subprocess.TimeoutExpired:
        raise RunnerError(f"the scan took longer than {limit:.0f} seconds and was stopped") from None

    if result.returncode == 2:
        host = urlparse(url).hostname
        raise RunnerError(f"{host} is not an allowed host. Add it to ALLOWED_HOSTS in .env to scan it.")
    if result.returncode != 0:
        raise RunnerError(f"the scan failed: {read_error(job_dir, result)}")

    json_path = job_dir / "inspection.json"
    try:
        inspection = Inspection.model_validate_json(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError(f"the runner's result could not be read: {exc}") from exc

    db.save_inspection(inspection, json_path)
    return inspection
