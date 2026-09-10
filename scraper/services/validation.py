"""Job configuration validation before activation or run."""

from __future__ import annotations

import re
from typing import Any, Mapping

from django.conf import settings

from scraper.constants import (
    FIELD_NAME_RE,
    JOB_STATUS_ACTIVE,
    PAGINATION_NEXT,
    PAGINATION_QUERY,
    PAGINATION_TEMPLATE,
    PLACEHOLDER_SELECTOR_TOKEN,
    RESERVED_FIELD_NAMES,
    SCOPE_DETAIL_PAGE,
    SOURCE_HTML_ATTRIBUTE,
    SOURCE_HTML_ELEMENT,
)

from .ssrf import RequestPolicyError, validate_url
from .url_template import placeholders
from .variables import detect_cycles


class JobValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def field_name_from_label(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
    if slug and slug[0].isdigit():
        slug = f"field_{slug}"
    return slug or "field"


def validate_identifier(name: str) -> str | None:
    if not name or not re.match(FIELD_NAME_RE, name):
        return "Names must match ^[a-z][a-z0-9_]*$."
    if name in RESERVED_FIELD_NAMES or name.startswith("_"):
        return "That name is reserved."
    return None


def validate_job_payload(payload: Mapping[str, Any], *, activating: bool = False) -> list[str]:
    errors: list[str] = []
    name = (payload.get("name") or "").strip()
    if not name:
        errors.append("Job name is required.")

    start_url = (payload.get("start_url") or "").strip()
    url_template = (payload.get("url_template") or "").strip()
    if activating or start_url:
        if not start_url:
            errors.append("A starting URL is required.")
        else:
            try:
                validate_url(start_url, resolve=False)
            except RequestPolicyError as exc:
                errors.append(str(exc))

    variables = list(payload.get("variables") or [])
    fields = list(payload.get("fields") or [])
    names = [item.get("name") for item in variables]
    if len(names) != len(set(names)):
        errors.append("Variable names must be unique.")
    for item in variables:
        ident = validate_identifier(item.get("name") or "")
        if ident:
            errors.append(f"Variable {item.get('name')!r}: {ident}")
        if item.get("source_type") in {SOURCE_HTML_ELEMENT, SOURCE_HTML_ATTRIBUTE} and not item.get("selector"):
            errors.append(f"Variable {item.get('name')} needs a CSS selector.")
        if item.get("source_type") == SOURCE_HTML_ATTRIBUTE and not item.get("attribute_name"):
            errors.append(f"Variable {item.get('name')} needs an attribute name.")
    cycles = detect_cycles(variables)
    if cycles:
        errors.append(f"Circular variable dependencies: {'; '.join(cycles)}")

    field_names = [item.get("name") for item in fields]
    if len(field_names) != len(set(field_names)):
        errors.append("Output field names must be unique.")
    for item in fields:
        ident = validate_identifier(item.get("name") or "")
        if ident:
            errors.append(f"Field {item.get('name')!r}: {ident}")
        if item.get("extraction_method") == "attribute" and not item.get("attribute_name"):
            errors.append(f"Field {item.get('name')} needs an attribute name.")
        if activating and PLACEHOLDER_SELECTOR_TOKEN in (item.get("selector") or ""):
            errors.append(f"Field {item.get('name')} still uses a placeholder selector.")

    if activating and not fields:
        errors.append("At least one output field is required.")
    detail_fields = [item for item in fields if item.get("scope") == SCOPE_DETAIL_PAGE]
    if activating and detail_fields and not payload.get("follow_detail_pages"):
        errors.append("Detail page fields exist but following detail pages is disabled.")
    if activating and (
        PLACEHOLDER_SELECTOR_TOKEN in (payload.get("result_selector") or "")
        or PLACEHOLDER_SELECTOR_TOKEN in (payload.get("detail_link_selector") or "")
    ):
        errors.append("Replace placeholder result selectors before activating or running the job.")

    template_vars = placeholders(url_template)
    defined = {item.get("name") for item in variables}
    missing = [name for name in template_vars if name not in defined]
    if url_template and missing:
        errors.append(f"URL template references undefined variables: {', '.join(missing)}.")

    pagination = payload.get("pagination_settings") or {}
    mode = pagination.get("mode")
    if mode in {PAGINATION_QUERY, PAGINATION_TEMPLATE} and not (url_template or pagination.get("url_template")):
        if activating:
            errors.append("Pagination needs a URL template or query parameter.")
    if mode in {PAGINATION_NEXT} and activating and not pagination.get("next_button_selector"):
        errors.append("Next-button pagination needs a selector.")

    unique_field = payload.get("unique_field_name") or ""
    if unique_field and unique_field not in field_names and unique_field not in defined:
        errors.append("The unique field must exist on the job.")

    max_pages = payload.get("maximum_pages")
    platform_pages = getattr(settings, "SCRAPER_MAX_PAGES", 100)
    if max_pages and int(max_pages) > platform_pages:
        errors.append(f"Maximum pages cannot exceed {platform_pages}.")
    max_records = payload.get("maximum_records")
    platform_records = getattr(settings, "SCRAPER_MAX_RECORDS", 5000)
    if max_records and int(max_records) > platform_records:
        errors.append(f"Maximum records cannot exceed {platform_records}.")

    if activating and payload.get("status") == JOB_STATUS_ACTIVE and errors:
        pass
    return errors


def assert_ready(payload: Mapping[str, Any]) -> None:
    errors = validate_job_payload(payload, activating=True)
    if errors:
        raise JobValidationError(errors)
