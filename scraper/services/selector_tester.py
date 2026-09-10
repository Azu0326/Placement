"""Test CSS selectors against the latest fetched page."""

from __future__ import annotations

from scraper.constants import VALUE_ATTRIBUTE, VALUE_TEXT

from .html_parser import extract, parse_html, select
from .html_sanitize import sanitize_html
from .transforms import apply_pipeline


def test_selector(
    html: str,
    selector: str,
    *,
    scope_selector: str = "",
    value_from: str = VALUE_TEXT,
    attribute_name: str = "",
    transformations: list | None = None,
    multiple: bool = True,
    base_url: str = "",
    limit: int = 8,
) -> dict:
    if scope_selector:
        try:
            scopes = select(parse_html(html), scope_selector)
        except Exception as exc:
            return {"error": "invalid_selector", "message": str(exc), "matches": 0, "samples": []}
        samples = []
        total = 0
        for scope in scopes[:limit]:
            result = extract(
                scope,
                selector,
                value_from=value_from,
                attribute_name=attribute_name,
                multiple=multiple,
                base_url=base_url,
                include_html=True,
            )
            total += result.match_count
            if result.error:
                return {"error": "invalid_selector", "message": result.error, "matches": 0, "samples": []}
            raw = result.values[0] if result.values else None
            transformed = apply_pipeline(raw, transformations or [], base_url=base_url)
            samples.append(
                {
                    "raw": raw,
                    "transformed": transformed,
                    "html": sanitize_html(result.raw_html[0]) if result.raw_html else "",
                    "empty": raw in (None, ""),
                    "missing_attribute": value_from == VALUE_ATTRIBUTE and raw is None,
                }
            )
        warning = ""
        if total == 1 and len(html) > 500 and selector in {"html", "body", ":root"}:
            warning = "The selector matches the whole page rather than repeated records."
        return {"error": "", "matches": total, "samples": samples, "warning": warning}

    result = extract(
        html,
        selector,
        value_from=value_from,
        attribute_name=attribute_name,
        multiple=True,
        base_url=base_url,
        include_html=True,
    )
    if result.error:
        return {"error": "invalid_selector", "message": result.error, "matches": 0, "samples": []}
    samples = []
    for raw, snippet in zip(result.values[:limit], result.raw_html[:limit] or [""] * len(result.values[:limit])):
        samples.append(
            {
                "raw": raw,
                "transformed": apply_pipeline(raw, transformations or [], base_url=base_url),
                "html": sanitize_html(snippet),
                "empty": raw in (None, ""),
                "missing_attribute": value_from == VALUE_ATTRIBUTE and raw is None,
            }
        )
    warning = ""
    if result.match_count == 1 and "html" in selector.lower():
        warning = "The selector matches the complete page instead of repeated records."
    return {
        "error": "" if result.match_count else "no_match",
        "message": "" if result.match_count else "No matching elements.",
        "matches": result.match_count,
        "samples": samples,
        "warning": warning,
    }
