"""Checks the model's answer against the scan before the tester sees it."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from shared.schemas import Inspection, ModelSuggestion, Selection

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


@dataclass
class ValidationResult:
    suggestion: ModelSuggestion | None = None   # None whenever there are errors
    errors: list[str] = field(default_factory=list)    # answer is rejected
    warnings: list[str] = field(default_factory=list)  # answer is kept, tester is told

    @property
    def ok(self) -> bool:
        return self.suggestion is not None and not self.errors


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = _FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def validate_suggestion(raw_text: str | None, inspection: Inspection, selection: Selection) -> ValidationResult:
    result = ValidationResult()

    text = _strip_fences(raw_text or "")
    if not text:
        result.errors.append("The answer is empty. Return the JSON object described in the instructions.")
        return result
    try:
        data = json.loads(text)
    except ValueError as exc:
        result.errors.append(f"The answer is not valid JSON ({exc}). Return only the JSON object.")
        return result
    if not isinstance(data, dict):
        result.errors.append("The answer must be a JSON object, not a list or a single value.")
        return result

    try:
        suggestion = ModelSuggestion.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"]) or "answer"
            result.errors.append(f"Field '{where}': {err['msg']}.")
        return result

    cited = list(dict.fromkeys(suggestion.referenced_element_ids))
    unknown = [i for i in cited if inspection.get_element(i) is None]
    if unknown:
        result.errors.append(
            "These element ids are not in the scan: " + ", ".join(unknown)
            + ". Cite only ids from the provided elements."
        )
    if not cited:
        result.errors.append("The answer cites no elements. Cite the ids of the elements it talks about.")
    if not suggestion.summary.strip():
        result.errors.append("The summary is empty.")
    if result.errors:
        return result

    selected = list(dict.fromkeys(selection.element_ids))
    extra = [i for i in cited if i not in selected]
    if extra:
        result.warnings.append("The answer cites elements the tester did not select: " + ", ".join(extra) + ".")

    no_unique = [
        i for i in selected
        if (el := inspection.get_element(i)) is not None and el.best_locator is None
    ]
    asked = any(q.strip() for q in suggestion.clarifying_questions)
    if no_unique and not asked:
        result.warnings.append(
            "No unique locator exists for " + ", ".join(no_unique)
            + ", but the answer asks no clarifying question."
        )

    result.suggestion = suggestion
    return result