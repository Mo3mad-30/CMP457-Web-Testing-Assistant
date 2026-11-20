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
from datetime import datetime, timezone
from app import config
from app import config, db
import logging

logger = logging.getLogger(__name__)

def _log(record: ModelCallRecord, response_text: str | None) -> None:
    """Store one attempt. A broken database must never break the model call."""
    try:
        db.log_model_call(record, response_text)
    except Exception:
        logger.warning("Could not store model call record", exc_info=True)

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

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _to_gemini_request(messages: list[dict], json_mode: bool) -> dict:
    """Convert OpenAI-style messages to Gemini's request body."""
    system_parts: list[str] = []
    contents: list[dict] = []
    for m in messages:
        text = m.get("content", "")
        if m.get("role") == "system":
            system_parts.append(text)
        else:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": text}]})

    body: dict = {"contents": contents}
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    return body


def call_gemini(
    messages: list[dict],
    model: str,
    api_key: str,
    json_mode: bool = True,
    client: httpx.Client | None = None,
    timeout: float = REQUEST_TIMEOUT,
) -> ProviderOutcome:
    """One request to Gemini's generateContent endpoint."""
    if not api_key:
        return ProviderOutcome("error", 0, error="GEMINI_API_KEY is not set")

    url = f"{GEMINI_BASE}/{model}:generateContent"
    body = _to_gemini_request(messages, json_mode)
    headers = {"x-goog-api-key": api_key}  # in a header, never in the URL

    start = time.perf_counter()
    try:
        if client is None:
            with httpx.Client(timeout=timeout) as own_client:
                resp = own_client.post(url, json=body, headers=headers)
        else:
            resp = client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        return ProviderOutcome("error", _ms_since(start), error=type(exc).__name__)
    latency = _ms_since(start)

    if resp.status_code == 429:
        return ProviderOutcome("rate_limited", latency, error="HTTP 429")
    if resp.status_code >= 400:
        return ProviderOutcome("error", latency, error=f"HTTP {resp.status_code}")

    try:
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return ProviderOutcome("error", latency, error="unexpected response shape")
    if not text:
        return ProviderOutcome("error", latency, error="empty response")

    answer_tokens = usage.get("candidatesTokenCount")
    thinking_tokens = usage.get("thoughtsTokenCount") or 0
    completion = None if answer_tokens is None else answer_tokens + thinking_tokens

    return ProviderOutcome(
        "ok",
        latency,
        text=text,
        prompt_tokens=usage.get("promptTokenCount"),
        completion_tokens=completion,
    )

# def call_model(
#     messages: list[dict],
#     purpose: str,
#     inspection_id: str | None = None,
#     json_mode: bool = True,
# ) -> ModelResult:
#     """Send messages to the primary model, retry once, then fall back (steps 3-6)."""
#     raise NotImplementedError("call_model is built in steps 3 to 6")

RETRY_WAIT_SECONDS = 2.0  # pause before the single retry of the primary model


def _send(provider: str, messages: list[dict], model: str, api_key: str, json_mode: bool) -> ProviderOutcome:
    if provider == "groq":
        return call_groq(messages, model, api_key, json_mode)
    if provider == "gemini":
        return call_gemini(messages, model, api_key, json_mode)
    return ProviderOutcome("error", 0, error=f"unknown provider '{provider}'")


def _api_key(provider: str) -> str:
    s = config.settings
    return {"groq": s.groq_api_key, "gemini": s.gemini_api_key}.get(provider, "")


def _record(
    outcome: ProviderOutcome,
    provider: str,
    model: str,
    purpose: str,
    inspection_id: str | None,
    is_fallback: bool = False,
    fallback_reason: str | None = None,
) -> ModelCallRecord:
    return ModelCallRecord(
        provider=provider,
        model=model,
        purpose=purpose,
        inspection_id=inspection_id,
        prompt_tokens=outcome.prompt_tokens,
        completion_tokens=outcome.completion_tokens,
        latency_ms=outcome.latency_ms,
        status=outcome.status,
        is_fallback=is_fallback,
        fallback_reason=fallback_reason,
        created_at=datetime.now(timezone.utc),
    )


def call_model(
    messages: list[dict],
    purpose: str,
    inspection_id: str | None = None,
    json_mode: bool = True,
) -> ModelResult:
    """Primary model -> one retry -> fallback model (if configured). Never raises on provider failure."""
    s = config.settings  # read at call time so tests can swap settings
    result = ModelResult(text=None, provider=s.model_provider, model=s.model_name)

    # def attempt(provider: str, model: str, is_fallback: bool = False, reason: str | None = None) -> ProviderOutcome:
    #     outcome = _send(provider, messages, model, _api_key(provider), json_mode)
    #     result.attempts.append(
    #         _record(outcome, provider, model, purpose, inspection_id, is_fallback, reason)
    #     )
    #     return outcome

    def attempt(provider: str, model: str, is_fallback: bool = False, reason: str | None = None) -> ProviderOutcome:
        outcome = _send(provider, messages, model, _api_key(provider), json_mode)
        record = _record(outcome, provider, model, purpose, inspection_id, is_fallback, reason)
        result.attempts.append(record)
        _log(record, outcome.text if outcome.status == "ok" else None)
        if outcome.status != "ok":
            logger.warning("%s/%s attempt failed (%s): %s", provider, model, outcome.status, outcome.error)
        return outcome

    # 1. primary, then one retry after a short wait
    outcome = attempt(s.model_provider, s.model_name)
    if outcome.status != "ok":
        time.sleep(RETRY_WAIT_SECONDS)
        outcome = attempt(s.model_provider, s.model_name)
    if outcome.status == "ok":
        result.text = outcome.text
        return result

    # 2. fallback, only if one is configured
    if not (s.fallback_provider and s.fallback_model_name):
        return result
    reason = f"{s.model_provider} {outcome.status} after retry"
    fb = attempt(s.fallback_provider, s.fallback_model_name, is_fallback=True, reason=reason)
    if fb.status == "ok":
        result.text = fb.text
        result.provider = s.fallback_provider
        result.model = s.fallback_model_name
        result.is_fallback = True
        result.fallback_reason = reason
    return result