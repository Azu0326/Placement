"""Generate a scraper job config from a page URL via OpenAI.

No views or persistence — this is a testable service function.
The API key is read from OPENAI_API_KEY and is never logged.

Output is a list of config-CSV rows (VARIABLE, RESULT_SELECTION, RESULT_FIELD)
so it can feed the existing import pipeline.
"""

from __future__ import annotations

import json
import os
import re

from bs4 import BeautifulSoup, Comment, FeatureNotFound

from scraper.constants import (
    CSV_ROW_RESULT_FIELD,
    CSV_ROW_RESULT_SELECTION,
    CSV_ROW_VARIABLE,
    DATA_CURRENCY,
    DATA_DATE,
    DATA_EMAIL,
    DATA_INTEGER,
    DATA_LONG_TEXT,
    DATA_TEXT,
    DATA_URL,
    PAGINATION_NEXT,
    PAGINATION_NONE,
    PAGINATION_QUERY,
    PAGINATION_TEMPLATE,
    SCOPE_RESULT_ITEM,
    SCOPE_RESULT_PAGE,
    SCOPE_VARIABLE,
    SOURCE_COUNTER,
    SOURCE_HTML_ATTRIBUTE,
    SOURCE_HTML_ELEMENT,
    VALUE_ATTRIBUTE,
    VALUE_EXISTS,
    VALUE_INNER_HTML,
    VALUE_TEXT,
)

from .http_fetcher import fetch_http

OPENAI_MODEL = "gpt-4o-mini"
TRIMMED_HTML_MAX_CHARS = 80_000

_STRIP_TAGS = ("script", "style", "noscript", "svg", "iframe", "canvas")
_ALLOWED_ROW_TYPES = (CSV_ROW_VARIABLE, CSV_ROW_RESULT_SELECTION, CSV_ROW_RESULT_FIELD)
_SOURCES = (SOURCE_COUNTER, SOURCE_HTML_ELEMENT, SOURCE_HTML_ATTRIBUTE)
_VALUE_FROM = (VALUE_TEXT, VALUE_ATTRIBUTE, VALUE_INNER_HTML, VALUE_EXISTS, "counter")
_DATA_TYPES = (DATA_TEXT, DATA_LONG_TEXT, DATA_INTEGER, DATA_URL, DATA_EMAIL, DATA_DATE, DATA_CURRENCY)
_PAGINATION_MODES = (PAGINATION_QUERY, PAGINATION_TEMPLATE, PAGINATION_NEXT, PAGINATION_NONE)
_TRANSFORMS = "trim, normalize_whitespace, absolute_url, parse_date, parse_integer, parse_currency"


class AIConfigError(ValueError):
    """Raised when the page cannot be turned into a usable config."""


def generate_config_from_url(url: str) -> list[dict]:
    """Fetch ``url``, ask the model for config-CSV rows, and return the list."""
    page = fetch_http(url)
    trimmed = trim_html(page.html)
    if not trimmed:
        raise AIConfigError("The page had no usable HTML after trimming.")
    raw = _complete_config(url=page.final_url or url, html=trimmed)
    return _parse_model_json(raw)


def trim_html(html: str) -> str:
    """Drop scripts, styles, comments and extra whitespace; keep structure and text."""
    try:
        soup = BeautifulSoup(html or "", "lxml")
    except FeatureNotFound:
        soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    compact = re.sub(r"[ \t\f\v]+", " ", str(soup))
    compact = re.sub(r">\s+<", "><", compact)
    compact = re.sub(r"\n\s*\n+", "\n", compact).strip()
    if len(compact) > TRIMMED_HTML_MAX_CHARS:
        return compact[:TRIMMED_HTML_MAX_CHARS]
    return compact


def _api_key() -> str:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise AIConfigError("OPENAI_API_KEY is not set.")
    return key


def _complete_config(*, url: str, html: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=_api_key())
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(url, html)},
            ],
        )
    except Exception as exc:
        raise AIConfigError("The model request failed.") from exc
    choices = getattr(response, "choices", None) or []
    if not choices or not getattr(choices[0].message, "content", None):
        raise AIConfigError("The model returned an empty response.")
    return choices[0].message.content


def _parse_model_json(text: str) -> list[dict]:
    raw = (text or "").strip()
    if not raw:
        raise AIConfigError("The model returned an empty response.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            raise AIConfigError("The model did not return valid JSON.")
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIConfigError("The model did not return valid JSON.") from exc
    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("rows"), list):
        rows = parsed["rows"]
    else:
        raise AIConfigError("The model JSON must be a list of config rows.")
    if not rows:
        raise AIConfigError("The model returned no config rows.")
    if not all(isinstance(row, dict) for row in rows):
        raise AIConfigError("Each config row must be an object.")
    return rows


def _user_prompt(url: str, html: str) -> str:
    return (
        f"Page URL: {url}\n\n"
        "Trimmed HTML:\n"
        f"{html}\n"
    )


_SYSTEM_PROMPT = f"""You propose a ScrapOS scraper configuration from one listing page.

Return ONLY valid JSON — no markdown, no commentary. Top-level shape:

{{
  "rows": [ <one object per config row> ]
}}

Each row uses the config-CSV column names. Allowed row_type values this version: {", ".join(_ALLOWED_ROW_TYPES)}.
Do NOT emit DETAIL_FIELD rows.

Columns (use these names; omit unused ones or set them to ""):
row_type, name, display_label, source, scope, selector_or_parameter, value_from, attribute_name,
data_type, start_value, increment, required, multiple_values, transform, unique, include_in_output,
sort_order, result_selector, detail_link_selector, follow_detail_page, pagination_mode,
maximum_pages, maximum_records, wait_for_selector, enabled, url_template, next_button_selector, confidence

Valid values:
- source: {", ".join(_SOURCES)}
- scope: {SCOPE_VARIABLE}, {SCOPE_RESULT_PAGE}, {SCOPE_RESULT_ITEM}
- value_from: {", ".join(_VALUE_FROM)}
- data_type: {", ".join(_DATA_TYPES)}
- pagination_mode: {", ".join(_PAGINATION_MODES)}
- transform: pipe-separated from {_TRANSFORMS} (CSV alias absolute_url is allowed)
- booleans (required, unique, enabled, include_in_output, follow_detail_page, multiple_values): "true" or "false"
- name: lowercase identifier matching ^[a-z][a-z0-9_]*$
- confidence (RESULT_FIELD only): "high" or "low"

Row recipes:

1) {CSV_ROW_VARIABLE} — ONLY when pagination uses a url_template containing {{{{variable}}}} (typically {{{{page}}}}).
   The variable named in the template MUST be declared as a VARIABLE row or the config is INVALID.
   Example for {{{{page}}}}:
   row_type={CSV_ROW_VARIABLE}, name=page, display_label=Page Number, source={SOURCE_COUNTER}, scope={SCOPE_VARIABLE},
   selector_or_parameter=page, value_from=counter, data_type={DATA_INTEGER}, start_value=1, increment=1,
   required=true, include_in_output=false, pagination_mode={PAGINATION_QUERY}, enabled=true
   If pagination_mode is {PAGINATION_NEXT} or {PAGINATION_NONE}, do NOT emit a VARIABLE row.

2) {CSV_ROW_RESULT_SELECTION} — exactly one row.
   name like listing_results, source={SOURCE_HTML_ELEMENT}, scope={SCOPE_RESULT_PAGE},
   result_selector = CSS selector matching EACH repeating result card,
   detail_link_selector = selector relative to that card (or ""),
   follow_detail_page = true only if a real detail link exists (still no DETAIL_FIELD rows),
   pagination_mode = one of the valid modes,
   wait_for_selector = same as result_selector,
   maximum_pages=100, maximum_records=500, enabled=true
   If pagination uses a page number / query / template:
     pagination_mode={PAGINATION_QUERY} or {PAGINATION_TEMPLATE},
     url_template = the listing URL with {{{{page}}}} (or the real variable name) in place of the page value.
     CRITICAL: every {{{{name}}}} in url_template MUST have a matching VARIABLE row whose name is exactly that name.
     Missing VARIABLE rows make the config invalid.
   If pagination is a next control: pagination_mode={PAGINATION_NEXT}, set next_button_selector, no VARIABLE row.
   If no pagination: pagination_mode={PAGINATION_NONE}, empty url_template, no VARIABLE row.

3) {CSV_ROW_RESULT_FIELD} — one row per field visible ON THE LISTING CARD (not the detail page).
   source={SOURCE_HTML_ELEMENT} or {SOURCE_HTML_ATTRIBUTE}, scope={SCOPE_RESULT_ITEM},
   selector_or_parameter = CSS selector relative to result_selector (not the document root),
   value_from={VALUE_TEXT} or {VALUE_ATTRIBUTE} (set attribute_name, usually href/src, when value_from is {VALUE_ATTRIBUTE}),
   include_in_output=true, enabled=true, confidence=high only when the selector clearly matches repeating items.
   Typical transforms: trim|normalize_whitespace for text; trim|absolute_url for URLs.

Rules:
- Prefer stable class/id selectors over nth-child paths.
- Do not invent fields that are not visible in the HTML.
- Do not emit DETAIL_FIELD, system fields, or placeholder selectors containing REPLACE_WITH_VERIFIED.
- Names must be unique within each row_type.
"""
