"""Ties prompt, model and validation together for the 'Ask model' button."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from app import db, model_client, prompts, validation
from app.model_client import ModelResult
from shared.schemas import Inspection, ModelCallRecord, ModelSuggestion, Selection

PURPOSE = "summarize_selection"
MAX_ECHO = 2000  # characters of a rejected answer that are sent back to the model


@dataclass
class AskResult:
    suggestion: ModelSuggestion | None = None            # only ever a validated suggestion
    errors: list[str] = field(default_factory=list)      # shown to the tester when there is no suggestion
    warnings: list[str] = field(default_factory=list)    # validation warnings on an accepted suggestion
    result: ModelResult | None = None                    # provider, model, fallback info and every attempt


def _tried(result: ModelResult) -> str:
    return ", ".join(f"{a.provider} {a.status}" for a in result.attempts) or "no attempts"


def _mark_last_invalid(result: ModelResult) -> ModelResult:
    """Copy of the result whose last attempt (the one that answered) is marked invalid_output."""
    attempts: list[ModelCallRecord] = list(result.attempts)
    if attempts:
        attempts[-1] = attempts[-1].model_copy(update={"status": "invalid_output"})
    return dataclasses.replace(result, attempts=attempts)


def _retry_prompt(errors: list[str]) -> str:
    listed = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous answer was rejected for these reasons:\n" + listed
        + "\n\nAnswer again with only the JSON object described in the instructions, fixing these problems."
    )


def summarize(inspection: Inspection, selection: Selection) -> AskResult:
    """Prompt -> model -> validation. One retry (with the errors listed) if the answer is invalid."""
    messages = prompts.build_summary_messages(inspection, selection)

    first = model_client.call_model(messages, PURPOSE, inspection.inspection_id)
    if first.text is None:
        return AskResult(errors=[f"No model answered ({_tried(first)}). Try again in a minute."], result=first)

    check = validation.validate_suggestion(first.text, inspection, selection)
    if check.ok:
        return AskResult(check.suggestion, [], check.warnings, first)

    first = _mark_last_invalid(first)
    retry_messages = messages + [
        {"role": "assistant", "content": first.text[:MAX_ECHO]},
        {"role": "user", "content": _retry_prompt(check.errors)},
    ]
    second = model_client.call_model(retry_messages, PURPOSE, inspection.inspection_id)
    combined = dataclasses.replace(second, attempts=first.attempts + second.attempts)
    if second.text is None:
        return AskResult(
            errors=[f"The first answer was invalid and the retry got no answer ({_tried(second)})."],
            result=combined,
        )

    check = validation.validate_suggestion(second.text, inspection, selection)
    if check.ok:
        return AskResult(check.suggestion, [], check.warnings, combined)

    return AskResult(
        errors=["Invalid output: the model's answer failed validation twice."] + check.errors,
        result=_mark_last_invalid(combined),
    )


def summarize_selection(inspection_id: str) -> AskResult:
    """Plan 6.7 entry point: load the scan and its latest saved selection, then summarize."""
    inspection = db.get_inspection(inspection_id)
    if inspection is None:
        return AskResult(errors=["Inspection not found."])
    selection = db.get_latest_selection(inspection_id)
    if selection is None:
        return AskResult(errors=["Save a selection and a testing goal before asking the model."])
    return summarize(inspection, selection)