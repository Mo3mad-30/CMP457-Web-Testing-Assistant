"""Route tests for Person A's pages: scan, history, screenshot."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, main, runner_client
from shared.schemas import Inspection

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample_inspection.json"
FIXTURE_URL = (runner_client.FIXTURES_DIR / "login.html").resolve().as_uri()


@pytest.fixture
def client(isolated_settings):
    with TestClient(main.app) as c:
        yield c


def test_home_page_has_scan_form(client):
    page = client.get("/").text
    assert 'action="/scan"' in page and 'name="scope"' in page
    assert "a browser window will open" in page


def test_scan_redirects_to_the_new_findings_page(client, monkeypatch):
    sample = Inspection.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    seen = {}

    def fake_run(url, scope=None):
        seen.update(url=url, scope=scope)
        return sample
    monkeypatch.setattr(runner_client, "run_inspection", fake_run)

    resp = client.post("/scan", data={"url": "https://www.saucedemo.com", "scope": "#login"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/inspections/{sample.inspection_id}"
    assert seen == {"url": "https://www.saucedemo.com", "scope": "#login"}


def test_scan_error_is_shown_on_the_form(client, monkeypatch):
    def failing(url, scope=None):
        raise runner_client.RunnerError("evil.example.com is not an allowed host. Add it to ALLOWED_HOSTS in .env to scan it.")
    monkeypatch.setattr(runner_client, "run_inspection", failing)

    resp = client.post("/scan", data={"url": "https://evil.example.com"})
    assert resp.status_code == 400
    assert "is not an allowed host" in resp.text
    assert 'value="https://evil.example.com"' in resp.text  # the tester's input is kept


def test_real_scan_appears_in_history_with_its_screenshot(client):
    resp = client.post("/scan", data={"url": FIXTURE_URL}, follow_redirects=False)
    assert resp.status_code == 303
    inspection_id = resp.headers["location"].rsplit("/", 1)[-1]

    history = client.get("/history").text
    assert inspection_id in history and "Fixture Login" in history

    shot = client.get(f"/inspections/{inspection_id}/screenshot")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"


def test_empty_history(client):
    assert "No scans yet" in client.get("/history").text


def test_unknown_screenshot_is_404(client):
    assert client.get("/inspections/insp-nope/screenshot").status_code == 404


def test_screenshot_outside_jobs_folder_is_never_served(client, isolated_settings, tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not for the browser")
    insp = Inspection.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    insp = insp.model_copy(update={"inspection_id": "insp-evil", "screenshot_path": str(secret)})
    json_path = tmp_path / "evil.json"
    json_path.write_text(insp.model_dump_json(), encoding="utf-8")
    db.save_inspection(insp, json_path)
    assert client.get("/inspections/insp-evil/screenshot").status_code == 404
