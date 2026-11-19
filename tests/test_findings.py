"""Person B: validate Task 5 against the agreed sample without Task 3/7b."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from app.main import app
from shared.schemas import Inspection, ModelCallRecord, ModelSuggestion, Selection


client = TestClient(app)


def test_findings_sample_page_and_missing_screenshot():
    response = client.get('/inspections/sample')
    assert response.status_code == 200
    for expected in ('Swag Labs', 'el-001', 'el-002', 'el-003', 'Username',
                     'All locator candidates', 'No screenshot available',
                     'Refine inspection scope', 'History', 'Save selection', 'Ask model'):
        assert expected in response.text


def test_selection_valid_and_invalid():
    invalid = client.post('/inspections/sample/select', data={'goal': 'test login now'})
    assert invalid.status_code == 400
    unknown = client.post('/inspections/sample/select', data={
        'element_ids': ['el-999'], 'goal': 'test login now'})
    assert unknown.status_code == 400
    short = client.post('/inspections/sample/select', data={
        'element_ids': ['el-001'], 'goal': 'login'})
    assert short.status_code == 400
    good = client.post('/inspections/sample/select', data={
        'element_ids': ['el-001', 'el-002', 'el-003'],
        'goal': 'verify login rejects a wrong password'})
    assert good.status_code == 200
    assert 'Selection saved' in good.text
    assert 'value="el-001"' in good.text
    assert client.get('/inspections/sample').text.count('checked') >= 3


def test_model_panel_mock_ask_result():
    # C's types are not present yet; test the specified attribute contract.
    from types import SimpleNamespace
    env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'app/templates'))
    call1 = ModelCallRecord(provider='groq', model='openai/gpt-oss-120b',
        purpose='summarize_selection', latency_ms=350, status='rate_limited',
        created_at=datetime.now(timezone.utc))
    call2 = ModelCallRecord(provider='gemini', model='gemini-flash',
        purpose='summarize_selection', latency_ms=450, status='ok', is_fallback=True,
        fallback_reason='groq rate_limited after retry', prompt_tokens=50,
        completion_tokens=20, created_at=datetime.now(timezone.utc))
    ask = SimpleNamespace(
        errors=[], warnings=['Review the locator'],
        suggestion=ModelSuggestion(summary='Login fields', referenced_element_ids=['el-001'],
            suggested_next_action='Draft a negative login test',
            clarifying_questions=['Which password is invalid?']),
        result=SimpleNamespace(provider='gemini', model='gemini-flash',
            is_fallback=True, fallback_reason='groq rate_limited after retry',
            attempts=[call1, call2]))
    html = env.get_template('_model_panel.html').render(ask=ask)
    for text in ('Login fields', 'el-001', 'Draft a negative login test',
                 'Which password is invalid?', 'Fallback model answered',
                 '50', '20', '450 ms', 'Earlier / failed model attempts',
                 'rate_limited'):
        assert text in html
