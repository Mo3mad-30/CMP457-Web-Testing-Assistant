"""Model client: the only place in the app that talks to a language model.

Names and signatures follow plan.md section 6.7. The behavior is built step by step:
provider calls, retry, fallback and logging.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.schemas import ModelCallRecord


@dataclass
class ModelResult:
    """What every caller gets back from call_model."""
    text: str | None                      # None when every attempt failed
    provider: str                         # provider that produced the final outcome
    model: str
    is_fallback: bool = False             # True when the fallback model answered
    fallback_reason: str | None = None    # e.g. "groq rate_limited after retry"
    attempts: list[ModelCallRecord] = field(default_factory=list)  # every attempt, in order


def call_model(
    messages: list[dict],
    purpose: str,
    inspection_id: str | None = None,
    json_mode: bool = True,
) -> ModelResult:
    """Send messages to the primary model, retry once, then fall back (steps 3-6)."""
    raise NotImplementedError("call_model is built in steps 3 to 6")