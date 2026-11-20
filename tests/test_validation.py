import json
from datetime import datetime, timezone
from pathlib import Path

from app.validation import validate_suggestion
from shared.schemas import Element, Inspection, Locator, Selection

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample_inspection.json"


def load_sample() -> Inspection:
    return Inspection.model_validate_json(SAMPLE.read_text(encoding="utf-8"))


def make_selection(ids) -> Selection:
    return Selection(
        inspection_id="insp-0001", element_ids=list(ids), goal="verify login", created_at=datetime.now(timezone.utc)
    )


def answer(**override) -> str:
    data = {
        "summary": "Username and password fields of the login form.",
        "referenced_element_ids": ["el-001", "el-002"],
        "suggested_next_action": "Draft a negative login test.",
        "clarifying_questions": [],
    }
    data.update(override)
    return json.dumps(data)


def no_unique_locator_inspection() -> Inspection:
    help_link = Element(
        element_id="el-900", tag="a", text="Help",
        locators=[Locator(strategy="text", value='get_by_text("Help")', match_count=2)],
    )
    base = load_sample()
    return base.model_copy(update={"elements": [*base.elements, help_link]})


def test_valid_answer_is_accepted():
    r = validate_suggestion(answer(), load_sample(), make_selection(["el-001", "el-002"]))
    assert r.ok and r.errors == [] and r.warnings == []
    assert r.suggestion.referenced_element_ids == ["el-001", "el-002"]


def test_json_in_code_fences_is_accepted():
    r = validate_suggestion("```json\n" + answer() + "\n```", load_sample(), make_selection(["el-001", "el-002"]))
    assert r.ok


def test_invalid_json_is_rejected():
    r = validate_suggestion("Sure! Here is my answer", load_sample(), make_selection(["el-001"]))
    assert r.suggestion is None
    assert "not valid JSON" in r.errors[0]


def test_json_that_is_not_an_object_is_rejected():
    r = validate_suggestion("[1, 2]", load_sample(), make_selection(["el-001"]))
    assert r.suggestion is None and r.errors


def test_missing_field_is_rejected_and_named():
    data = json.loads(answer())
    del data["summary"]
    r = validate_suggestion(json.dumps(data), load_sample(), make_selection(["el-001"]))
    assert r.suggestion is None
    assert any("summary" in e for e in r.errors)


def test_unknown_element_id_is_rejected():
    r = validate_suggestion(
        answer(referenced_element_ids=["el-001", "el-099"]), load_sample(), make_selection(["el-001"])
    )
    assert r.suggestion is None
    assert any("el-099" in e for e in r.errors)


def test_empty_output_is_rejected():
    for raw in (None, "", "   "):
        r = validate_suggestion(raw, load_sample(), make_selection(["el-001"]))
        assert r.suggestion is None and r.errors


def test_citing_an_unselected_but_real_element_is_a_warning():
    r = validate_suggestion(answer(), load_sample(), make_selection(["el-001"]))
    assert r.suggestion is not None and r.errors == []
    assert any("el-002" in w for w in r.warnings)


def test_answer_citing_no_elements_is_a_warning():
    r = validate_suggestion(answer(referenced_element_ids=[]), load_sample(), make_selection(["el-001"]))
    assert r.suggestion is not None
    assert any("cites no elements" in w for w in r.warnings)


def test_missing_unique_locator_without_a_question_is_a_warning():
    r = validate_suggestion(
        answer(referenced_element_ids=["el-900"]), no_unique_locator_inspection(), make_selection(["el-900"])
    )
    assert r.suggestion is not None
    assert any("el-900" in w and "unique" in w for w in r.warnings)


def test_a_clarifying_question_clears_the_missing_locator_warning():
    r = validate_suggestion(
        answer(referenced_element_ids=["el-900"], clarifying_questions=["Which Help link should be tested?"]),
        no_unique_locator_inspection(),
        make_selection(["el-900"]),
    )
    assert r.suggestion is not None and r.warnings == []