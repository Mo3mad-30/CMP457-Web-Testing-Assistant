"""Shared data contract between the runner, the web app and the model prompts.

The runner PRODUCES an Inspection. The app STORES and DISPLAYS it.
The model only ever sees elements taken from it, and its answers are checked against it.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field

# ---------------------------------------------------------------------------
# Inspection output (written by runner/inspect_page.py)
# ---------------------------------------------------------------------------

LocatorStrategy = Literal["role", "label", "placeholder", "test_id", "text", "id", "css"]


class Locator(BaseModel):
    """One way to find an element, and how many elements it matched on the live page."""
    strategy: LocatorStrategy
    value: str                      # e.g. 'get_by_role("button", name="Login")'
    match_count: int                # measured by the runner, never guessed

    @computed_field
    @property
    def is_unique(self) -> bool:
        return self.match_count == 1


class BoundingBox(BaseModel):
    """Where the element sits in the screenshot (pixels), used to highlight it in the UI."""
    x: float
    y: float
    width: float
    height: float


class Element(BaseModel):
    """One interactive element as observed on the page."""
    element_id: str                 # "el-001"; unique within one inspection, cited by the model
    tag: str                        # "input", "button", "a", ...
    role: Optional[str] = None      # accessible role: "textbox", "button", "link", ...
    accessible_name: Optional[str] = None
    text: Optional[str] = None      # visible text, trimmed
    label: Optional[str] = None     # text of an associated <label>, if any
    attributes: dict[str, str] = Field(default_factory=dict)  # id, name, type, placeholder, href, data-test...
    css_path: Optional[str] = None  # structural fallback, also helps the Phase 2 rescan diff
    visible: bool = True
    enabled: bool = True
    bounding_box: Optional[BoundingBox] = None
    locators: list[Locator] = Field(default_factory=list)  # ranked, best first

    @computed_field
    @property
    def best_locator(self) -> Optional[Locator]:
        """First unique locator in rank order; None means the tester must be asked."""
        return next((loc for loc in self.locators if loc.is_unique), None)


class Inspection(BaseModel):
    """Everything one scan observed. Stored as-is and never overwritten."""
    inspection_id: str
    url: str                        # URL the tester asked for
    final_url: str                  # URL after redirects (the real source page)
    title: str
    scanned_at: datetime
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1280, "height": 800})
    scope_selector: Optional[str] = None   # e.g. "form#login"; None = whole page
    screenshot_path: Optional[str] = None
    elements: list[Element] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # e.g. "3 elements hidden", "iframe skipped"

    @computed_field
    @property
    def element_count(self) -> int:
        return len(self.elements)

    def get_element(self, element_id: str) -> Optional[Element]:
        return next((e for e in self.elements if e.element_id == element_id), None)


# ---------------------------------------------------------------------------
# Human interaction (saved when the tester selects elements / writes a goal)
# ---------------------------------------------------------------------------

class Selection(BaseModel):
    inspection_id: str
    element_ids: list[str]
    goal: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Model interaction
# ---------------------------------------------------------------------------

class ModelSuggestion(BaseModel):
    """The JSON shape the model must return. Validated before the tester sees it."""
    summary: str                            # what the selected elements are / do
    referenced_element_ids: list[str]       # every element the answer talks about
    suggested_next_action: str              # e.g. "Draft a negative login test"
    clarifying_questions: list[str] = Field(default_factory=list)  # asked when evidence is missing


class ModelCallRecord(BaseModel):
    """One row of usage evidence: logged for every call, successful or not."""
    provider: str                   # "groq" / "gemini"
    model: str                      # "openai/gpt-oss-120b"
    purpose: str                    # "summarize_selection" (Phase 2: "draft_tests", "generate_code", ...)
    inspection_id: Optional[str] = None
    prompt_tokens: Optional[int] = None      # from the API response, not estimated
    completion_tokens: Optional[int] = None
    latency_ms: int
    status: Literal["ok", "invalid_output", "rate_limited", "error"]
    is_fallback: bool = False                # True when this attempt went to the fallback model
    fallback_reason: Optional[str] = None    # e.g. "groq rate_limited after retry"
    created_at: datetime
