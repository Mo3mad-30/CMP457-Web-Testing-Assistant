"""Runner client tests: the real inspector runs as a separate process against the local test page."""
import re
import subprocess

import pytest

from app import db, runner_client
from app.runner_client import RunnerError

FIXTURE_URL = (runner_client.FIXTURES_DIR / "login.html").resolve().as_uri()


def test_inspection_id_format():
    assert re.fullmatch(r"insp-\d{8}-\d{6}-[0-9a-f]{4}", runner_client.new_inspection_id())


def test_minimal_env_never_contains_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = runner_client.minimal_env()
    assert "GROQ_API_KEY" not in env and "GEMINI_API_KEY" not in env
    assert "secret-groq" not in env.values()
    assert env["PATH"] == "/usr/bin"


@pytest.mark.parametrize("url", ["ftp://example.com", "javascript:alert(1)", "https://", "not a url"])
def test_validate_url_rejects_non_web_addresses(url):
    with pytest.raises(RunnerError):
        runner_client.validate_url(url)


def test_validate_url_allows_only_fixture_files(tmp_path):
    runner_client.validate_url(FIXTURE_URL)  # our test page is fine
    outside = tmp_path / "secret.html"
    outside.write_text("<p>private</p>")
    with pytest.raises(RunnerError, match="tests/fixtures"):
        runner_client.validate_url(outside.as_uri())


def test_command_passes_settings_and_scope(isolated_settings, tmp_path):
    cmd = runner_client.build_command("https://www.saucedemo.com", tmp_path, "insp-x", "#login")
    assert cmd[1:3] == ["-m", "runner.inspect_page"]
    assert cmd[cmd.index("--allowed-hosts") + 1] == "www.saucedemo.com"
    assert cmd[cmd.index("--scope") + 1] == "#login"
    assert "--headless" in cmd


def test_scan_runs_saves_and_never_overwrites(isolated_settings):
    first = runner_client.run_inspection(FIXTURE_URL)
    second = runner_client.run_inspection(FIXTURE_URL, scope="#login")

    assert first.inspection_id != second.inspection_id
    assert first.element_count == 10 and second.element_count == 5
    job = isolated_settings.data_dir / "jobs" / first.inspection_id
    assert (job / "inspection.json").exists() and (job / "screenshot.png").exists()
    assert db.get_inspection(first.inspection_id) == first
    assert [r["inspection_id"] for r in db.list_inspections()] == [second.inspection_id, first.inspection_id]


def test_host_not_allowed_gives_a_helpful_message(isolated_settings, monkeypatch):
    monkeypatch.setattr(runner_client, "allowed_hosts_for", lambda url: ["www.saucedemo.com"])
    with pytest.raises(RunnerError, match="ALLOWED_HOSTS"):
        runner_client.run_inspection("https://not-allowed.example.com")
    assert db.list_inspections() == []


def test_runner_failure_shows_its_error(isolated_settings):
    missing = (runner_client.FIXTURES_DIR / "does-not-exist.html").resolve().as_uri()
    with pytest.raises(RunnerError, match="the scan failed"):
        runner_client.run_inspection(missing)


def test_timeout_is_reported(isolated_settings, monkeypatch):
    def too_slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="runner", timeout=kwargs["timeout"])
    monkeypatch.setattr(runner_client.subprocess, "run", too_slow)
    with pytest.raises(RunnerError, match="longer than"):
        runner_client.run_inspection(FIXTURE_URL)
