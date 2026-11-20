"""Model client: the only place in the app that talks to a language model.

Names and signatures follow plan.md section 6.7. The behavior is built step by step:
provider calls, retry, fallback and logging.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.schemas import ModelCallRecord

import time
from typing import Literal

import httpx

@dataclass
class ModelResult:
    """What every caller gets back from call_model."""
    text: str | None                      # None when every attempt failed
    provider: str                         # provider that produced the final outcome
    model: str
    is_fallback: bool = False             # True when the fallback model answered
    fallback_reason: str | None = None    # e.g. "groq rate_limited after retry"
    attempts: list[ModelCallRecord] = field(default_factory=list)  # every attempt, in order

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
REQUEST_TIMEOUT = 30.0  # seconds


@dataclass
class ProviderOutcome:
    """Result of one request to one provider (no retry or fallback logic here)."""
    status: Literal["ok", "rate_limited", "error"]
    latency_ms: int
    text: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None  # short, key-free description for failures


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def call_groq(
    messages: list[dict],
    model: str,
    api_key: str,
    json_mode: bool = True,
    client: httpx.Client | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> ProviderOutcome:
    """One request to Groq's OpenAI-compatible chat endpoint."""
    if not api_key:
        return ProviderOutcome("error", 0, error="GROQ_API_KEY is not set")

    body: dict = {"model": model, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}"}

    start = time.perf_counter()
    try:
        if client is None:
            with httpx.Client(timeout=timeout) as own_client:
                resp = own_client.post(GROQ_URL, json=body, headers=headers)
        else:
            resp = client.post(GROQ_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        # Only the exception class name: never the request, so the key cannot leak.
        return ProviderOutcome("error", _ms_since(start), error=type(exc).__name__)
    latency = _ms_since(start)

    if resp.status_code == 429:
        return ProviderOutcome("rate_limited", latency, error="HTTP 429")
    if resp.status_code >= 400:
        return ProviderOutcome("error", latency, error=f"HTTP {resp.status_code}")

    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return ProviderOutcome("error", latency, error="unexpected response shape")
    if not text:
        return ProviderOutcome("error", latency, error="empty response")

    return ProviderOutcome(
        "ok",
        latency,
        text=text,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )

def call_model(
    messages: list[dict],
    purpose: str,
    inspection_id: str | None = None,
    json_mode: bool = True,
) -> ModelResult:
    """Send messages to the primary model, retry once, then fall back (steps 3-6)."""
    raise NotImplementedError("call_model is built in steps 3 to 6")