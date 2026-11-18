"""The sample inspection must always load into the shared schema (it is the team's contract)."""
import json
from pathlib import Path

from shared.schemas import Inspection

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample_inspection.json"


def load_sample() -> Inspection:
    return Inspection.model_validate(json.loads(SAMPLE.read_text(encoding="utf-8")))


def test_sample_loads():
    insp = load_sample()
    assert insp.element_count == len(insp.elements) > 0


def test_element_ids_are_unique():
    ids = [e.element_id for e in load_sample().elements]
    assert len(ids) == len(set(ids))


def test_best_locator_is_unique_when_present():
    for el in load_sample().elements:
        if el.best_locator is not None:
            assert el.best_locator.match_count == 1


def test_get_element():
    insp = load_sample()
    assert insp.get_element("el-001").attributes["id"] == "user-name"
    assert insp.get_element("el-999") is None
