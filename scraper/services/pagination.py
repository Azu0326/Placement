"""Pagination controllers and stop-rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from scraper.constants import (
    PAGINATION_EXTRACTED,
    PAGINATION_INFINITE,
    PAGINATION_LOAD_MORE,
    PAGINATION_NEXT,
    PAGINATION_NONE,
    PAGINATION_QUERY,
    PAGINATION_TEMPLATE,
    STOP_EMPTY_PAGES,
    STOP_MAX_PAGES,
    STOP_MAX_RECORDS,
    STOP_MAX_RUNTIME,
    STOP_NEXT_DISABLED,
    STOP_NEXT_MISSING,
    STOP_NO_NEW_DETAIL_URLS,
    STOP_NO_NEW_UNIQUE,
    STOP_NO_RESULT_ITEMS,
    STOP_REPEATED_NEXT_URL,
    STOP_REPEATED_PAGE,
    STOP_REQUEST_FAILURES,
    STOP_USER_CANCEL,
    VALUE_ATTRIBUTE,
)

from .html_parser import extract
from .url_template import render


@dataclass
class PaginationState:
    page: int
    url: str
    fingerprints: list[str] = field(default_factory=list)
    next_urls: list[str] = field(default_factory=list)
    empty_pages: int = 0
    failures: int = 0
    unique_keys: set[str] = field(default_factory=set)
    detail_urls: set[str] = field(default_factory=set)
    stop_reason: str = ""


def next_listing_url(
    settings: Mapping[str, Any],
    state: PaginationState,
    *,
    html: str = "",
    variables: Mapping[str, Any] | None = None,
) -> str | None:
    mode = settings.get("mode") or PAGINATION_NONE
    if mode == PAGINATION_NONE:
        return None
    if mode in {PAGINATION_QUERY, PAGINATION_TEMPLATE}:
        template = settings.get("url_template") or ""
        values = dict(variables or {})
        values.setdefault(settings.get("variable") or "page", state.page + 1)
        if template:
            return render(template, values)
        return _replace_query(state.url, settings.get("parameter") or "page", state.page + 1)
    if mode in {PAGINATION_NEXT, PAGINATION_LOAD_MORE, PAGINATION_INFINITE, PAGINATION_EXTRACTED}:
        selector = settings.get("next_button_selector") or settings.get("next_url_selector") or ""
        if not selector:
            return None
        result = extract(
            html,
            selector,
            value_from=settings.get("next_attribute") or VALUE_ATTRIBUTE,
            attribute_name=settings.get("next_attribute_name") or "href",
            base_url=state.url,
        )
        if not result.values or not result.values[0]:
            return None
        return urljoin(state.url, str(result.values[0]))
    return None


def _replace_query(url: str, parameter: str, value: int) -> str:
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != parameter]
    pairs.append((parameter, str(value)))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(pairs), ""))


def should_stop(
    settings: Mapping[str, Any],
    state: PaginationState,
    *,
    result_count: int,
    new_unique: int,
    new_details: int,
    next_url: str | None,
    next_disabled: bool,
    fingerprint: str,
    cancelled: bool,
    runtime_exceeded: bool,
    records_created: int,
    max_pages: int,
    max_records: int,
) -> str:
    rules = set(settings.get("stop_conditions") or [])
    if cancelled and (not rules or STOP_USER_CANCEL in rules):
        return STOP_USER_CANCEL
    if runtime_exceeded:
        return STOP_MAX_RUNTIME
    if max_pages and state.page >= max_pages:
        return STOP_MAX_PAGES
    if max_records and records_created >= max_records:
        return STOP_MAX_RECORDS
    if STOP_NO_RESULT_ITEMS in rules and result_count == 0:
        return STOP_NO_RESULT_ITEMS
    if STOP_EMPTY_PAGES in rules and result_count == 0:
        if state.empty_pages + 1 >= int(settings.get("empty_page_limit", 2)):
            return STOP_EMPTY_PAGES
    if STOP_NO_NEW_UNIQUE in rules and result_count and new_unique == 0:
        return STOP_NO_NEW_UNIQUE
    if STOP_NO_NEW_DETAIL_URLS in rules and result_count and new_details == 0:
        return STOP_NO_NEW_DETAIL_URLS
    if fingerprint and fingerprint in state.fingerprints and (not rules or STOP_REPEATED_PAGE in rules):
        return STOP_REPEATED_PAGE
    if next_url and next_url in state.next_urls and (not rules or STOP_REPEATED_NEXT_URL in rules):
        return STOP_REPEATED_NEXT_URL
    if next_disabled and STOP_NEXT_DISABLED in rules:
        return STOP_NEXT_DISABLED
    if next_url is None and settings.get("mode") in {PAGINATION_NEXT, PAGINATION_LOAD_MORE, PAGINATION_EXTRACTED}:
        if not rules or STOP_NEXT_MISSING in rules:
            return STOP_NEXT_MISSING
    if state.failures >= int(settings.get("failure_limit", 3)):
        return STOP_REQUEST_FAILURES
    return ""
