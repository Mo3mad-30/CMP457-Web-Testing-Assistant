"""Task 5 routes on real saved scans (storage from Task 3), using the isolated_settings fixture."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, main
from shared.schemas import Inspection

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample_inspection.json"
SCAN_ID = "insp-20261120-120000-abcd"


@pytest.fixture
def client(isolated_settings):
    with TestClient(main.app) as c:
        yield c


def save_scan(settings, with_screenshot=False, **element_updates) -> Inspection:
    """Store the sample under a real-looking id, as the runner client would."""
    insp = Inspection.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    job_dir = settings.data_dir / "jobs" / SCAN_ID
    job_dir.mkdir(parents=True)
    shot = job_dir / "screenshot.png"
    if with_screenshot:
        shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    elements = list(insp.elements)
    if element_updates:
        elements[0] = elements[0].model_copy(update=element_updates)
    insp = insp.model_copy(update={"inspection_id": SCAN_ID, "screenshot_path": str(shot), "elements": elements})
    json_path = job_dir / "inspection.json"
    json_path.write_text(insp.model_dump_json(), encoding="utf-8")
    db.save_inspection(insp, json_path)
    return insp


def test_real_saved_scan_renders(client, isolated_settings):
    insp = save_scan(isolated_settings, with_screenshot=True)
    page = client.get(f"/inspections/{SCAN_ID}")
    assert page.status_code == 200
    html = page.text
    assert SCAN_ID in html and insp.final_url in html
    for el in insp.elements:
        assert f'value="{el.element_id}"' in html
    assert f'src="/inspections/{SCAN_ID}/screenshot"' in html
    assert 'action="/scan"' in html and f'name="url" value="{insp.url}"' in html
    head = html.split("</head>")[0]
    assert "app.css" in head and "app.js" in head  # page assets go in base.html's head block


def test_sample_renders_without_screenshot(client):
    page = client.get("/inspections/sample")
    assert page.status_code == 200
    assert "No screenshot available" in page.text


def test_unknown_inspection_is_404(client):
    assert client.get("/inspections/insp-nope").status_code == 404


def test_select_saves_and_rerenders_with_message(client, isolated_settings):
    save_scan(isolated_settings)
    goal = "verify login rejects a wrong password"
    resp = client.post(f"/inspections/{SCAN_ID}/select",
                       data={"element_ids": ["el-001", "el-003"], "goal": goal})
    assert resp.status_code == 200
    assert "Selection saved" in resp.text
    saved = db.get_latest_selection(SCAN_ID)
    assert saved.element_ids == ["el-001", "el-003"] and saved.goal == goal
    page = client.get(f"/inspections/{SCAN_ID}").text
    assert 'value="el-001" aria-label="Select el-001" checked' in page
    assert 'value="el-002" aria-label="Select el-002" checked' not in page


@pytest.mark.parametrize("data, message", [
    ({"goal": "verify login rejects a wrong password"}, "Select at least one element."),
    ({"element_ids": ["el-001"], "goal": "login"}, "at least three words"),
    ({"element_ids": ["el-001", "el-999"], "goal": "verify login rejects a wrong password"},
     "element not found in this inspection"),
])
def test_invalid_selection_is_refused(client, isolated_settings, data, message):
    save_scan(isolated_settings)
    resp = client.post(f"/inspections/{SCAN_ID}/select", data=data)
    assert resp.status_code == 400
    assert message in resp.text
    assert db.get_latest_selection(SCAN_ID) is None


def test_page_content_is_escaped(client, isolated_settings):
    evil = "<script>alert(1)</script>"
    save_scan(isolated_settings, accessible_name=evil, label=evil,
              attributes={"placeholder": evil, "data-x": "' onmouseover='alert(2)"})
    html = client.get(f"/inspections/{SCAN_ID}").text
    assert evil not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "' onmouseover='alert(2)" not in html
