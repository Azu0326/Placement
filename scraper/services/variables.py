"""Resolve configured variables from URLs, HTML, counters and system values."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from scraper.constants import (
    SOURCE_COUNTER,
    SOURCE_FIXED,
    SOURCE_HTML_ATTRIBUTE,
    SOURCE_HTML_ELEMENT,
    SOURCE_LIST,
    SOURCE_PAGE_NUMBER,
    SOURCE_PARENT_RECORD,
    SOURCE_REGEX,
    SOURCE_REQUEST_URL,
    SOURCE_RUN_TIMESTAMP,
    SOURCE_SYSTEM,
    SOURCE_URL_PATH,
    SOURCE_URL_QUERY,
    VALUE_ATTRIBUTE,
)

from .html_parser import extract
from .transforms import apply_pipeline, regex_capture
from .types import normalize


class VariableError(ValueError):
    pass


def detect_cycles(variables: list[Mapping[str, Any]]) -> list[str]:
    graph: dict[str, set[str]] = {}
    for item in variables:
        name = item.get("name") or ""
        depends = set()
        for key in ("depends_on", "parent"):
            value = (item.get("configuration") or {}).get(key) or item.get(key)
            if value:
                depends.add(str(value))
        graph[name] = depends
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[str] = []

    def walk(node: str, stack: list[str]) -> None:
        if node in visiting:
            cycles.append(" -> ".join(stack + [node]))
            return
        if node in visited or node not in graph:
            return
        visiting.add(node)
        for nxt in graph[node]:
            walk(nxt, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for name in graph:
        walk(name, [])
    return cycles


def resolve_variable(
    spec: Mapping[str, Any],
    *,
    url: str = "",
    html: str = "",
    page_number: int = 1,
    parent: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    base_url: str = "",
) -> Any:
    source = spec.get("source_type")
    config = spec.get("configuration") or {}
    value_from = spec.get("value_from") or VALUE_ATTRIBUTE
    selector = spec.get("selector") or ""
    attribute = spec.get("attribute_name") or config.get("attribute_name") or ""
    now = now or datetime.now(timezone.utc)
    value: Any = spec.get("default_value")

    if source == SOURCE_URL_QUERY:
        key = config.get("parameter") or spec.get("name")
        value = parse_qs(urlparse(url).query).get(key, [None])[0]
    elif source == SOURCE_URL_PATH:
        index = int(config.get("segment_index", -1))
        parts = [part for part in urlparse(url).path.split("/") if part]
        try:
            value = parts[index]
        except IndexError:
            value = None
    elif source == SOURCE_COUNTER:
        start = int(config.get("start_value", config.get("start", 1)))
        increment = int(config.get("increment", 1))
        value = start + increment * max(page_number - 1, 0)
        maximum = config.get("maximum_value", config.get("maximum"))
        if maximum is not None and value > int(maximum):
            value = int(maximum)
    elif source == SOURCE_FIXED:
        value = config.get("value", spec.get("default_value"))
    elif source == SOURCE_LIST:
        values = config.get("values") or []
        index = max(page_number - 1, 0)
        value = values[index] if index < len(values) else None
    elif source in {SOURCE_HTML_ELEMENT, SOURCE_HTML_ATTRIBUTE}:
        if source == SOURCE_HTML_ATTRIBUTE:
            value_from = VALUE_ATTRIBUTE
            attribute = attribute or config.get("attribute_name") or "href"
        result = extract(
            html,
            selector,
            value_from=value_from,
            attribute_name=attribute,
            multiple=bool(spec.get("multiple")),
            base_url=base_url or url,
        )
        if result.error:
            raise VariableError(result.error)
        value = result.values if spec.get("multiple") else (result.values[0] if result.values else None)
    elif source == SOURCE_REGEX:
        result = extract(
            html,
            selector or "body",
            value_from="text_content",
            multiple=False,
            base_url=base_url or url,
        )
        text = result.values[0] if result.values else ""
        value = regex_capture(text, pattern=config.get("pattern") or "")
    elif source == SOURCE_PAGE_NUMBER:
        value = page_number
    elif source == SOURCE_REQUEST_URL:
        value = url
    elif source == SOURCE_PARENT_RECORD:
        field = config.get("field") or spec.get("name")
        value = (parent or {}).get(field)
    elif source == SOURCE_SYSTEM:
        value = str(uuid4())
    elif source == SOURCE_RUN_TIMESTAMP:
        value = now.isoformat()
    else:
        raise VariableError(f"Unknown variable source: {source}.")

    value = apply_pipeline(value, spec.get("transformations") or [], base_url=base_url or url)
    if value in (None, "", []) and spec.get("default_value") not in (None, ""):
        value = spec["default_value"]
    if spec.get("required") and value in (None, "", []):
        raise VariableError(f"Variable {spec.get('name')} is required.")
    return normalize(value, spec.get("data_type") or "text", multiple=bool(spec.get("multiple")))
