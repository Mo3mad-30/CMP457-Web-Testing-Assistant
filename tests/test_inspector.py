"""Inspector tests against the local test page.

They run the inspector exactly as the app will: as a separate process, from the project root.
The browser is headless here so the tests can run anywhere.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared.schemas import Inspection

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_URL = (ROOT / "tests" / "fixtures" / "login.html").resolve().as_uri()


def run_inspector(out_dir: Path, *extra: str, url: str = FIXTURE_URL) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "runner.inspect_page", "--url", url, "--out", str(out_dir), "--headless", *extra]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)


def load(out_dir: Path) -> Inspection:
    return Inspection.model_validate_json((out_dir / "inspection.json").read_text(encoding="utf-8"))


def by_name(insp: Inspection, name: str):
    return [e for e in insp.elements if e.accessible_name == name]


@pytest.fixture(scope="module")
def default_scan(tmp_path_factory):
    out = tmp_path_factory.mktemp("default")
    result = run_inspector(out)
    assert result.returncode == 0, result.stderr
    return out, load(out)


def test_writes_valid_inspection_and_screenshot(default_scan):
    out, insp = default_scan
    assert insp.title == "Fixture Login"
    assert (out / "screenshot.png").exists()
    ids = [e.element_id for e in insp.elements]
    assert ids == [f"el-{i:03d}" for i in range(1, len(ids) + 1)]


def test_finds_ten_visible_elements_and_warns_about_hidden(default_scan):
    _, insp = default_scan
    assert insp.element_count == 10
    assert "1 hidden element(s) skipped" in insp.warnings
    assert all(e.visible for e in insp.elements)


def test_labeled_inputs_have_unique_label_locators(default_scan):
    _, insp = default_scan
    for name in ("Username", "Password"):
        (el,) = by_name(insp, name)
        assert el.label == name
        label_locs = [l for l in el.locators if l.strategy == "label"]
        assert label_locs and label_locs[0].match_count == 1


def test_password_has_no_role(default_scan):
    _, insp = default_scan
    (pw,) = by_name(insp, "Password")
    assert pw.role is None
    assert not any(l.strategy == "role" for l in pw.locators)


def test_login_button_has_test_id_locator(default_scan):
    _, insp = default_scan
    (btn,) = by_name(insp, "Log in")
    assert any(l.value == 'get_by_test_id("login-btn")' and l.match_count == 1 for l in btn.locators)


def test_duplicate_help_links_are_not_unique(default_scan):
    _, insp = default_scan
    links = by_name(insp, "Help")
    assert len(links) == 2
    for link in links:
        role_loc = next(l for l in link.locators if l.strategy == "role")
        assert role_loc.match_count == 2 and not role_loc.is_unique
        assert link.best_locator.strategy == "id"


def test_aria_label_only_button_gets_its_name(default_scan):
    _, insp = default_scan
    (gear,) = by_name(insp, "Open settings")
    assert gear.best_locator.value == 'get_by_role("button", name="Open settings", exact=True)'


def test_disabled_button_is_marked(default_scan):
    _, insp = default_scan
    (btn,) = by_name(insp, "Disabled action")
    assert btn.enabled is False


def test_every_kept_locator_matches_something(default_scan):
    _, insp = default_scan
    assert all(l.match_count >= 1 for e in insp.elements for l in e.locators)


def test_include_hidden(tmp_path):
    assert run_inspector(tmp_path, "--include-hidden").returncode == 0
    insp = load(tmp_path)
    assert insp.element_count == 11
    assert [e.accessible_name for e in insp.elements if not e.visible] == ["Hidden"]


def test_scope_limits_elements_to_the_form(tmp_path):
    assert run_inspector(tmp_path, "--scope", "#login").returncode == 0
    insp = load(tmp_path)
    assert insp.scope_selector == "#login"
    assert [e.accessible_name for e in insp.elements] == ["Username", "Password", "Remember me", "Language", "Log in"]


def test_scope_matching_nothing_warns(tmp_path):
    assert run_inspector(tmp_path, "--scope", "#does-not-exist").returncode == 0
    insp = load(tmp_path)
    assert insp.element_count == 0
    assert any("scope selector matched nothing" in w for w in insp.warnings)


def test_host_not_allowed_exits_2_with_error_file(tmp_path):
    result = run_inspector(tmp_path, "--allowed-hosts", "www.saucedemo.com", url="https://not-allowed.example.com")
    assert result.returncode == 2
    assert "host not allowed" in json.loads((tmp_path / "error.json").read_text())["error"]
    assert not (tmp_path / "inspection.json").exists()


def test_load_failure_exits_1_with_error_file(tmp_path):
    result = run_inspector(tmp_path, url=(tmp_path / "missing.html").as_uri())
    assert result.returncode == 1
    assert "error" in json.loads((tmp_path / "error.json").read_text())
