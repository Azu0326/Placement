"""Canonical configuration objects shared by manual forms and CSV import."""

from __future__ import annotations

from typing import Any, Mapping

from scraper.constants import (
    CSV_ROW_DETAIL_FIELD,
    CSV_ROW_RESULT_FIELD,
    CSV_ROW_RESULT_SELECTION,
    CSV_ROW_VARIABLE,
    ORIGIN_MANUAL,
    PLACEHOLDER_SELECTOR_TOKEN,
    SCOPE_DETAIL_PAGE,
    SCOPE_RESULT_ITEM,
    SCOPE_RESULT_PAGE,
    SCOPE_SYSTEM,
    SCOPE_VARIABLE,
    SOURCE_COUNTER,
    SOURCE_FIXED,
    SOURCE_HTML_ATTRIBUTE,
    SOURCE_HTML_ELEMENT,
    SOURCE_LIST,
    SOURCE_PAGE_NUMBER,
    SOURCE_REQUEST_URL,
    SOURCE_RUN_TIMESTAMP,
    VALUE_ATTRIBUTE,
    VALUE_EXISTS,
    VALUE_INNER_HTML,
    VALUE_TEXT,
)

from .transforms import REGISTRY
from .validation import validate_identifier

SOURCE_ALIASES = {
    "url_query_parameter": "url_query",
    "url_query": "url_query",
    "url_path_segment": "url_path",
    "url_path": "url_path",
    "counter": SOURCE_COUNTER,
    "fixed_value": SOURCE_FIXED,
    "fixed": SOURCE_FIXED,
    "list": SOURCE_LIST,
    "list_of_values": SOURCE_LIST,
    "html_element": SOURCE_HTML_ELEMENT,
    "html_attribute": SOURCE_HTML_ATTRIBUTE,
    "regex": "regex",
    "current_page_number": SOURCE_PAGE_NUMBER,
    "page_number": SOURCE_PAGE_NUMBER,
    "current_request_url": SOURCE_REQUEST_URL,
    "request_url": SOURCE_REQUEST_URL,
    "parent_record_value": "parent_record",
    "parent_record": "parent_record",
    "system_value": "system",
    "system": "system",
    "run_timestamp": SOURCE_RUN_TIMESTAMP,
}

SCOPE_ALIASES = {
    "result_page": SCOPE_RESULT_PAGE,
    "result_item": SCOPE_RESULT_ITEM,
    "detail_page": SCOPE_DETAIL_PAGE,
    "variable": SCOPE_VARIABLE,
    "system": SCOPE_SYSTEM,
}

VALUE_FROM_ALIASES = {
    "text_content": VALUE_TEXT,
    "inner_html": VALUE_INNER_HTML,
    "attribute": VALUE_ATTRIBUTE,
    "element_exists": VALUE_EXISTS,
    "existence": VALUE_EXISTS,
    "counter": VALUE_TEXT,
    "fixed_value": VALUE_TEXT,
    "list_value": VALUE_TEXT,
    "current_url": VALUE_TEXT,
    "current_page": VALUE_TEXT,
    "timestamp": VALUE_TEXT,
}

PAGINATION_ALIASES = {
    "none": "none",
    "query_parameter": "query_parameter",
    "url_template": "url_template",
    "next_link": "next_button",
    "next_button": "next_button",
    "load_more": "load_more",
    "infinite_scroll": "infinite_scroll",
    "extracted_url": "extracted_url",
}

TRANSFORM_ALIASES = {
    "absolute_url": "resolve_absolute_url",
    "resolve_absolute_url": "resolve_absolute_url",
}


def is_placeholder_selector(selector: str) -> bool:
    return PLACEHOLDER_SELECTOR_TOKEN in (selector or "")


def alias(mapping: Mapping[str, str], raw: str, *, default: str = "") -> str:
    value = (raw or "").strip().lower()
    if not value:
        return default
    return mapping.get(value, value)


def parse_bool(raw: Any, default: bool = False) -> bool:
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def parse_int(raw: Any, default: int | None = None) -> int | None:
    if raw in (None, ""):
        return default
    text = str(raw).strip()
    if not text or not text.lstrip("-").isdigit():
        raise ValueError(f"Not an integer: {raw!r}")
    return int(text)


def parse_transforms(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        names = raw
    else:
        names = [part.strip() for part in str(raw).split("|") if part.strip()]
    out = []
    for name in names:
        if isinstance(name, dict):
            out.append(name)
            continue
        mapped = TRANSFORM_ALIASES.get(str(name).strip(), str(name).strip())
        if mapped not in REGISTRY:
            raise ValueError(f"Unknown transform: {name}")
        out.append(mapped)
    return out


def normalize_variable(item: Mapping[str, Any], *, via: str = ORIGIN_MANUAL) -> dict:
    name = (item.get("name") or "").strip()
    source = alias(SOURCE_ALIASES, item.get("source_type") or item.get("source") or "", default=SOURCE_FIXED)
    scope = alias(SCOPE_ALIASES, item.get("scope") or "", default=SCOPE_RESULT_PAGE)
    value_from = alias(VALUE_FROM_ALIASES, item.get("value_from") or "", default=VALUE_TEXT)
    if source == SOURCE_HTML_ATTRIBUTE:
        value_from = VALUE_ATTRIBUTE
    configuration = dict(item.get("configuration") or {})
    if item.get("start_value") not in (None, ""):
        configuration["start_value"] = parse_int(item.get("start_value"), 1)
    if item.get("increment") not in (None, ""):
        configuration["increment"] = parse_int(item.get("increment"), 1)
    if item.get("fixed_value") not in (None, ""):
        configuration["fixed_value"] = item.get("fixed_value")
    if item.get("list_values") not in (None, ""):
        configuration["list_values"] = item.get("list_values")
    selector = (item.get("selector") or item.get("selector_or_parameter") or configuration.get("parameter") or "").strip()
    if selector and source in {SOURCE_COUNTER, "url_query"}:
        configuration.setdefault("parameter", selector)
    transforms = item.get("transformations")
    if item.get("transform") not in (None, ""):
        transforms = parse_transforms(item.get("transform"))
    return {
        "name": name,
        "label": (item.get("label") or item.get("display_label") or name).strip(),
        "source_type": source,
        "scope": scope,
        "selector": selector if source in {SOURCE_HTML_ELEMENT, SOURCE_HTML_ATTRIBUTE, "regex"} else "",
        "value_from": value_from,
        "attribute_name": (item.get("attribute_name") or "").strip(),
        "data_type": (item.get("data_type") or "text").strip() or "text",
        "configuration": configuration,
        "transformations": transforms or [],
        "default_value": item.get("default_value"),
        "required": parse_bool(item.get("required")),
        "multiple": parse_bool(item.get("multiple") if "multiple" in item else item.get("multiple_values")),
        "unique": parse_bool(item.get("unique")),
        "sort_order": parse_int(item.get("sort_order"), 0) or 0,
        "created_via": item.get("created_via") or via,
        "last_updated_via": item.get("last_updated_via") or via,
    }


def normalize_field(item: Mapping[str, Any], *, via: str = ORIGIN_MANUAL, row_type: str = "") -> dict:
    name = (item.get("name") or "").strip()
    source = alias(SOURCE_ALIASES, item.get("source_type") or item.get("source") or "", default=SOURCE_HTML_ELEMENT)
    scope = alias(SCOPE_ALIASES, item.get("scope") or "", default=SCOPE_RESULT_ITEM)
    if row_type == CSV_ROW_DETAIL_FIELD:
        scope = SCOPE_DETAIL_PAGE
    elif row_type == CSV_ROW_RESULT_FIELD and scope == SCOPE_DETAIL_PAGE:
        scope = SCOPE_RESULT_ITEM
    if source in {SOURCE_PAGE_NUMBER, SOURCE_REQUEST_URL, SOURCE_RUN_TIMESTAMP, "system"}:
        scope = SCOPE_SYSTEM
    extraction = alias(
        VALUE_FROM_ALIASES,
        item.get("extraction_method") or item.get("value_from") or "",
        default=VALUE_TEXT,
    )
    if source == SOURCE_HTML_ATTRIBUTE:
        extraction = VALUE_ATTRIBUTE
    transforms = item.get("transformations")
    if item.get("transform") not in (None, ""):
        transforms = parse_transforms(item.get("transform"))
    include = item.get("include_in_csv")
    if "include_in_output" in item:
        include = parse_bool(item.get("include_in_output"), True)
    elif include is None:
        include = True
    return {
        "name": name,
        "label": (item.get("label") or item.get("display_label") or name).strip(),
        "description": item.get("description") or "",
        "scope": scope,
        "selector": (item.get("selector") or item.get("selector_or_parameter") or "").strip(),
        "extraction_method": extraction,
        "attribute_name": (item.get("attribute_name") or "").strip(),
        "data_type": (item.get("data_type") or "text").strip() or "text",
        "transformations": transforms or [],
        "default_value": item.get("default_value"),
        "required": parse_bool(item.get("required")),
        "multiple": parse_bool(item.get("multiple") if "multiple" in item else item.get("multiple_values")),
        "unique": parse_bool(item.get("unique")),
        "include_in_csv": bool(include),
        "include_in_sqlite": bool(item.get("include_in_sqlite", include)),
        "sort_order": parse_int(item.get("sort_order"), 0) or 0,
        "created_via": item.get("created_via") or via,
        "last_updated_via": item.get("last_updated_via") or via,
        "source_type": source,
    }


def normalize_result_selection(item: Mapping[str, Any]) -> dict:
    return {
        "name": (item.get("name") or "results").strip(),
        "label": (item.get("label") or item.get("display_label") or "Results").strip(),
        "result_selector": (item.get("result_selector") or item.get("selector_or_parameter") or "").strip(),
        "detail_link_selector": (item.get("detail_link_selector") or "").strip(),
        "follow_detail_pages": parse_bool(
            item.get("follow_detail_pages") if "follow_detail_pages" in item else item.get("follow_detail_page")
        ),
        "pagination_mode": alias(PAGINATION_ALIASES, item.get("pagination_mode") or "", default="query_parameter"),
        "maximum_pages": parse_int(item.get("maximum_pages")),
        "maximum_records": parse_int(item.get("maximum_records")),
        "wait_for_selector": (item.get("wait_for_selector") or "").strip(),
        "unique_field_name": (item.get("unique_field_name") or "").strip(),
    }


def _issue(row: int, column: str, value: Any, code: str, message: str, suggestion: str = "") -> dict:
    return {
        "row": row,
        "column": column,
        "value": "" if value is None else str(value),
        "code": code,
        "message": message,
        "suggestion": suggestion,
    }


def validate_variable_item(item: Mapping[str, Any], *, row: int = 0) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []
    ident = validate_identifier(item.get("name") or "")
    if ident:
        errors.append(_issue(row, "name", item.get("name"), "invalid_name", ident, "Use a lowercase identifier such as page."))
    source = item.get("source_type")
    if source not in SOURCE_ALIASES.values() and source not in SOURCE_ALIASES:
        errors.append(_issue(row, "source", source, "unsupported_source", "Unsupported variable source.", "Use counter, html_element or another supported source."))
    if source in {SOURCE_HTML_ELEMENT, SOURCE_HTML_ATTRIBUTE} and not item.get("selector"):
        errors.append(_issue(row, "selector_or_parameter", "", "selector_required", "A CSS selector is required for HTML variables.", "Enter a selector such as h3.title."))
    if source == SOURCE_HTML_ATTRIBUTE and not item.get("attribute_name"):
        errors.append(
            _issue(
                row,
                "attribute_name",
                "",
                "attribute_name_required",
                "Attribute name is required when Value From is Attribute.",
                "Enter href, src or another valid HTML attribute.",
            )
        )
    if source == SOURCE_COUNTER:
        start = (item.get("configuration") or {}).get("start_value")
        increment = (item.get("configuration") or {}).get("increment")
        if start in (None, "") or increment in (None, ""):
            errors.append(_issue(row, "start_value", start, "counter_bounds_required", "Counter variables need a start value and increment.", "Use start_value=1 and increment=1."))
    if is_placeholder_selector(item.get("selector") or ""):
        warnings.append(_issue(row, "selector_or_parameter", item.get("selector"), "placeholder_selector", "Replace the placeholder selector before running the job.", "Inspect the live DOM and enter a stable selector."))
    return errors, warnings


def validate_field_item(item: Mapping[str, Any], *, row: int = 0) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []
    ident = validate_identifier(item.get("name") or "")
    if ident:
        errors.append(_issue(row, "name", item.get("name"), "invalid_name", ident, "Use a lowercase identifier such as scholarship_name."))
    system = item.get("scope") == SCOPE_SYSTEM or item.get("source_type") in {
        SOURCE_PAGE_NUMBER,
        SOURCE_REQUEST_URL,
        SOURCE_RUN_TIMESTAMP,
        "system",
    }
    if not system and not item.get("selector"):
        errors.append(_issue(row, "selector_or_parameter", "", "selector_required", "A CSS selector is required.", "Enter a selector relative to the result card or detail page."))
    if item.get("extraction_method") == VALUE_ATTRIBUTE and not item.get("attribute_name"):
        errors.append(
            _issue(
                row,
                "attribute_name",
                "",
                "attribute_name_required",
                "Attribute name is required when Value From is Attribute.",
                "Enter href, src or another valid HTML attribute.",
            )
        )
    if is_placeholder_selector(item.get("selector") or ""):
        warnings.append(_issue(row, "selector_or_parameter", item.get("selector"), "placeholder_selector", "Replace the placeholder selector before running the job.", "Inspect the live DOM and enter a stable selector."))
    return errors, warnings


def validate_result_selection(item: Mapping[str, Any], *, row: int = 0) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []
    if not item.get("result_selector"):
        errors.append(_issue(row, "result_selector", "", "result_selector_required", "A repeating result selector is required.", "Use a selector that matches each result card."))
    elif is_placeholder_selector(item.get("result_selector") or ""):
        warnings.append(_issue(row, "result_selector", item.get("result_selector"), "placeholder_selector", "Replace the placeholder result selector before running the job.", "Inspect the live DOM."))
    if item.get("follow_detail_pages") and not item.get("detail_link_selector"):
        errors.append(_issue(row, "detail_link_selector", "", "detail_link_required", "A detail-link selector is required when following detail pages.", "Enter a selector such as h3 a."))
    if is_placeholder_selector(item.get("detail_link_selector") or ""):
        warnings.append(_issue(row, "detail_link_selector", item.get("detail_link_selector"), "placeholder_selector", "Replace the placeholder detail-link selector before running the job.", "Inspect the live DOM."))
    if item.get("pagination_mode") and item["pagination_mode"] not in PAGINATION_ALIASES.values():
        errors.append(_issue(row, "pagination_mode", item.get("pagination_mode"), "unsupported_pagination", "Unsupported pagination mode.", "Use query_parameter, url_template, next_link, load_more, infinite_scroll or none."))
    return errors, warnings


def functional_variable(item: Mapping[str, Any]) -> dict:
    data = dict(item)
    data.pop("created_via", None)
    data.pop("last_updated_via", None)
    return data


def functional_field(item: Mapping[str, Any]) -> dict:
    data = dict(item)
    data.pop("created_via", None)
    data.pop("last_updated_via", None)
    data.pop("source_type", None)
    return data
