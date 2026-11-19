"""Inspector: opens a visible browser, reads one page and writes an Inspection JSON.

Runs as its own process (the isolation boundary), from the project root:
    python -m runner.inspect_page --url https://www.saucedemo.com --out data/jobs/manual-1

It may import only from `shared/`, never from `app/`.
Exit codes: 0 = inspection.json written, 1 = failure (error.json written),
            2 = host not allowed (error.json written).
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from shared.schemas import BoundingBox, Element, Inspection, Locator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_FAILED, EXIT_HOST_NOT_ALLOWED = 0, 1, 2
VIEWPORT = {"width": 1280, "height": 800}


# ---------------------------------------------------------------------------
# Part 2.1: command line and safety checks
# ---------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    """Read the command-line options (shared names, plan section 6.4)."""
    p = argparse.ArgumentParser(description="Inspect one web page and write inspection.json")
    p.add_argument("--url", required=True, help="Page to inspect")
    p.add_argument("--out", required=True, help="Job folder for inspection.json / screenshot.png / error.json")
    p.add_argument("--inspection-id", help="Defaults to the name of the --out folder")
    p.add_argument("--scope", help="CSS selector; only elements inside it are collected")
    p.add_argument("--allowed-hosts", default="", help="Comma-separated hosts; empty = host of --url only")
    p.add_argument("--timeout", type=float, default=30, help="Seconds allowed for loading the page")
    p.add_argument("--hold-seconds", type=float, default=0, help="Keep the browser open this long before closing")
    p.add_argument("--headless", action="store_true", help="Hide the browser (tests only; the demo uses a visible one)")
    p.add_argument("--include-hidden", action="store_true", help="Also list elements that are not visible")
    return p.parse_args(argv)


def resolve_allowed_hosts(url: str, raw: str) -> list[str]:
    """The hosts the runner may navigate to: the given list, or else only the URL's own host."""
    hosts = [h.strip().lower() for h in raw.split(",") if h.strip()]
    if hosts:
        return hosts
    own = urlparse(url).hostname
    return [own.lower()] if own else []


def host_allowed(url: str, allowed_hosts: list[str]) -> bool:
    """True for local files (our test pages) and for http(s) URLs whose host is on the list."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return True
    if parsed.scheme not in ("http", "https"):
        return False
    return (parsed.hostname or "").lower() in allowed_hosts


def write_error(out_dir: Path, message: str) -> None:
    """Report a failure the way the app expects: error.json in the job folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "error.json").write_text(json.dumps({"error": message}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Part 2.2: opening the page
# ---------------------------------------------------------------------------

def install_allowlist(page, allowed_hosts: list[str], warnings: list[str]) -> None:
    """Abort page navigations to other hosts; let images, scripts and styles load from anywhere."""
    def handle(route, request):
        url = request.url
        is_web = url.startswith(("http://", "https://"))
        if request.is_navigation_request() and is_web and not host_allowed(url, allowed_hosts):
            note = f"blocked navigation to {urlparse(url).hostname}"
            if note not in warnings:
                warnings.append(note)
            route.abort()
        else:
            route.continue_()

    page.route("**/*", handle)


def load_page(page, url: str, timeout_s: float, warnings: list[str]) -> None:
    """Open the URL and wait until the page is quiet; fall back to the plain load event."""
    timeout_ms = timeout_s * 1000
    try:
        response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    except PlaywrightTimeout:
        warnings.append("page never went network-idle; inspected after the load event")
        page.wait_for_load_state("load", timeout=timeout_ms)
        response = None
    if response is not None and response.status >= 400:
        warnings.append(f"page answered with HTTP {response.status}")


# ---------------------------------------------------------------------------
# Part 2.3: reading the page
# ---------------------------------------------------------------------------

INTERACTIVE_SELECTOR = (
    "a[href], button, input:not([type=hidden]), select, textarea, "
    "[role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem], "
    "[onclick], [contenteditable=true]"
)
KEPT_ATTRIBUTES = [
    "id", "name", "type", "placeholder", "href", "value", "aria-label", "title",
    "data-testid", "data-test", "role", "for", "disabled",
]

# Runs inside the browser. Returns null when the scope selector matches nothing.
COLLECT_JS = r"""
([selector, scope, kept]) => {
  const root = scope ? document.querySelector(scope) : document;
  if (!root) return null;
  const found = Array.from(root.querySelectorAll(selector));
  if (scope && root.matches(selector)) found.unshift(root);

  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const textOf = el => clean(el.innerText || el.textContent);
  const uniqueId = id => id && document.querySelectorAll("#" + CSS.escape(id)).length === 1;

  const labelOf = el => {
    if (el.labels && el.labels.length) return textOf(el.labels[0]) || null;
    const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    const text = clean(ids.map(i => { const n = document.getElementById(i); return n ? textOf(n) : ""; }).join(" "));
    return text || null;
  };

  const cssPath = el => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      if (uniqueId(node.id)) { parts.unshift("#" + CSS.escape(node.id)); break; }
      const tag = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (!parent) { parts.unshift(tag); break; }
      const same = Array.from(parent.children).filter(c => c.tagName === node.tagName);
      parts.unshift(same.length > 1 ? `${tag}:nth-of-type(${same.indexOf(node) + 1})` : tag);
      node = parent;
    }
    return parts.join(" > ");
  };

  return [...new Set(found)].map(el => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const attributes = {};
    for (const name of kept) {
      const v = el.getAttribute(name);
      if (v !== null && !(name === "value" && el.type === "password")) attributes[name] = v.slice(0, 200);
    }
    return {
      tag: el.tagName.toLowerCase(),
      text: textOf(el).slice(0, 120) || null,
      attributes,
      label: labelOf(el),
      explicit_role: el.getAttribute("role"),
      multiple: !!el.multiple,
      visible: r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none",
      enabled: !el.disabled && el.getAttribute("aria-disabled") !== "true",
      bbox: { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height },
      css_path: cssPath(el),
    };
  });
}
"""


def collect_raw_elements(page, scope: str | None) -> list[dict] | None:
    """Everything the browser can tell us about each interactive element (None = scope matched nothing)."""
    return page.evaluate(COLLECT_JS, [INTERACTIVE_SELECTOR, scope, KEPT_ATTRIBUTES])


# ---------------------------------------------------------------------------
# Part 2.4: understanding each element
# ---------------------------------------------------------------------------

INPUT_TYPE_ROLES = {
    "submit": "button", "button": "button", "reset": "button", "image": "button",
    "checkbox": "checkbox", "radio": "radio", "range": "slider", "number": "spinbutton",
    "search": "searchbox", "text": "textbox", "email": "textbox", "tel": "textbox", "url": "textbox",
    # "password" is missing on purpose: password inputs have no ARIA role.
}


def implicit_role(raw: dict) -> str | None:
    """The ARIA role Playwright's get_by_role will see: explicit role first, else the tag's default."""
    if raw["explicit_role"]:
        return raw["explicit_role"].split()[0]
    tag = raw["tag"]
    if tag == "a":
        return "link" if "href" in raw["attributes"] else None
    if tag == "button":
        return "button"
    if tag == "textarea":
        return "textbox"
    if tag == "select":
        return "listbox" if raw["multiple"] else "combobox"
    if tag == "input":
        return INPUT_TYPE_ROLES.get((raw["attributes"].get("type") or "text").lower())
    return None


def accessible_name(raw: dict, role: str | None) -> str | None:
    """Approximate accessible name. Approximate on purpose: role locators are verified by counting (2.5)."""
    attrs = raw["attributes"]
    if attrs.get("aria-label"):
        return attrs["aria-label"].strip()
    if raw["label"]:
        return raw["label"]
    if role in ("button", "link"):
        if raw["text"]:
            return raw["text"]
        if raw["tag"] == "input":
            default = "Submit" if attrs.get("type") == "submit" else None
            return attrs.get("value") or default
    return attrs.get("title") or attrs.get("placeholder") or None


# ---------------------------------------------------------------------------
# Part 2.5: locators
# ---------------------------------------------------------------------------

SIMPLE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def candidate_locators(raw: dict, role: str | None, name: str | None) -> list[tuple[str, str, list, dict]]:
    """Locator candidates in rank order, as (strategy, page method, args, kwargs)."""
    attrs = raw["attributes"]
    out = []
    if role and name:
        out.append(("role", "get_by_role", [role], {"name": name, "exact": True}))
    if raw["label"]:
        out.append(("label", "get_by_label", [raw["label"]], {"exact": True}))
    if attrs.get("placeholder"):
        out.append(("placeholder", "get_by_placeholder", [attrs["placeholder"]], {"exact": True}))
    if attrs.get("data-testid"):
        out.append(("test_id", "get_by_test_id", [attrs["data-testid"]], {}))
    if role in ("button", "link") and raw["text"] and len(raw["text"]) <= 40:
        out.append(("text", "get_by_text", [raw["text"]], {"exact": True}))
    if attrs.get("id"):
        el_id = attrs["id"]
        selector = f"#{el_id}" if SIMPLE_ID.fullmatch(el_id) else f"[id={json.dumps(el_id)}]"
        out.append(("id", "locator", [selector], {}))
    if attrs.get("data-test"):
        out.append(("css", "locator", [f"[data-test={json.dumps(attrs['data-test'])}]"], {}))
    if raw["css_path"]:
        out.append(("css", "locator", [raw["css_path"]], {}))
    return out


def format_call(method: str, args: list, kwargs: dict) -> str:
    """The Python call as text, e.g. get_by_role("button", name="Log in", exact=True)."""
    def lit(v):
        return repr(v) if isinstance(v, bool) else json.dumps(v)
    parts = [lit(a) for a in args] + [f"{k}={lit(v)}" for k, v in kwargs.items()]
    return f"{method}({', '.join(parts)})"


def count_matches(page, method: str, args: list, kwargs: dict) -> int:
    """How many elements this locator finds on the live page (0 if Playwright rejects it)."""
    try:
        return getattr(page, method)(*args, **kwargs).count()
    except Exception:
        return 0


def measured_locators(page, candidates) -> list[Locator]:
    """Count every candidate; drop those matching nothing, keep non-unique ones as evidence."""
    result, seen = [], set()
    for strategy, method, args, kwargs in candidates:
        value = format_call(method, args, kwargs)
        if value in seen:
            continue
        seen.add(value)
        count = count_matches(page, method, args, kwargs)
        if count > 0:
            result.append(Locator(strategy=strategy, value=value, match_count=count))
    return result


# ---------------------------------------------------------------------------
# Part 2.6: putting it together
# ---------------------------------------------------------------------------

def build_inspection(page, raw_elements: list[dict], *, inspection_id: str, url: str,
                     scope: str | None, include_hidden: bool, screenshot_path: str | None,
                     warnings: list[str]) -> Inspection:
    """Turn raw browser data into a validated Inspection with ids el-001, el-002, ... in page order."""
    elements, hidden = [], 0
    for raw in raw_elements:
        if not raw["visible"] and not include_hidden:
            hidden += 1
            continue
        role = implicit_role(raw)
        name = accessible_name(raw, role)
        box = raw["bbox"]
        elements.append(Element(
            element_id=f"el-{len(elements) + 1:03d}",
            tag=raw["tag"],
            role=role,
            accessible_name=name,
            text=raw["text"],
            label=raw["label"],
            attributes=raw["attributes"],
            css_path=raw["css_path"] or None,
            visible=raw["visible"],
            enabled=raw["enabled"],
            bounding_box=BoundingBox(**box) if box["width"] and box["height"] else None,
            locators=measured_locators(page, candidate_locators(raw, role, name)),
        ))
    if hidden:
        warnings.append(f"{hidden} hidden element(s) skipped")
    return Inspection(
        inspection_id=inspection_id,
        url=url,
        final_url=page.url,
        title=page.title(),
        scanned_at=datetime.now(timezone.utc),
        viewport=VIEWPORT,
        scope_selector=scope,
        screenshot_path=screenshot_path,
        elements=elements,
        warnings=warnings,
    )


def screenshot_rel_path(path: Path) -> str:
    """Screenshot path as stored in the JSON: relative to the project root when possible."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main(argv=None) -> int:
    """Run one inspection job and return the exit code."""
    args = parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    inspection_id = args.inspection_id or out_dir.name
    allowed = resolve_allowed_hosts(args.url, args.allowed_hosts)

    if not host_allowed(args.url, allowed):
        write_error(out_dir, f"host not allowed: {urlparse(args.url).hostname or args.url}")
        return EXIT_HOST_NOT_ALLOWED

    warnings: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=args.headless)
            try:
                page = browser.new_context(viewport=VIEWPORT).new_page()
                install_allowlist(page, allowed, warnings)
                load_page(page, args.url, args.timeout, warnings)

                raw = collect_raw_elements(page, args.scope)
                if raw is None:
                    warnings.append(f"scope selector matched nothing: {args.scope}")
                    raw = []
                if page.evaluate("document.querySelectorAll('iframe').length"):
                    warnings.append("iframes not inspected")

                shot = out_dir / "screenshot.png"
                page.screenshot(path=str(shot), full_page=True)

                inspection = build_inspection(
                    page, raw, inspection_id=inspection_id, url=args.url, scope=args.scope,
                    include_hidden=args.include_hidden, screenshot_path=screenshot_rel_path(shot),
                    warnings=warnings,
                )
                json_path = out_dir / "inspection.json"
                json_path.write_text(inspection.model_dump_json(indent=2), encoding="utf-8")

                if args.hold_seconds > 0:
                    time.sleep(args.hold_seconds)
            finally:
                browser.close()
    except Exception as exc:  # report every failure the same way
        write_error(out_dir, f"{type(exc).__name__}: {exc}")
        print(f"inspection failed: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(json_path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
