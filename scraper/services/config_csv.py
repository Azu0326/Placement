"""Parse, preview, import and export scraper configuration CSV."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction

from scraper.constants import (
    CSV_HEADERS,
    CSV_ROW_DETAIL_FIELD,
    CSV_ROW_RESULT_FIELD,
    CSV_ROW_RESULT_SELECTION,
    CSV_ROW_TYPES,
    CSV_ROW_VARIABLE,
    ORIGIN_CSV,
    ORIGIN_MANUAL,
)
from scraper.models import ScrapeField, ScrapeJob, VariableParameter
from scraper.services.config import (
    is_placeholder_selector,
    normalize_field,
    normalize_result_selection,
    normalize_variable,
    parse_bool,
    parse_int,
    parse_transforms,
    validate_field_item,
    validate_result_selection,
    validate_variable_item,
)
from scraper.services.jobs import apply_result_selection, save_field, save_variable
from scraper.services.snapshots import snapshot_job
from scraper.services.url_template import render

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class CsvConfigError(ValueError):
    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or [{"row": 0, "column": "", "value": "", "code": "csv_error", "message": message, "suggestion": ""}]


def _formula_safe(value: str) -> str:
    text = "" if value is None else str(value)
    if text[:1] in FORMULA_PREFIXES:
        return f"'{text}"
    return text


def _issue(row: int, column: str, value: Any, code: str, message: str, suggestion: str = "") -> dict:
    return {
        "row": row,
        "column": column,
        "value": "" if value is None else str(value),
        "code": code,
        "message": message,
        "suggestion": suggestion,
    }


def template_rows() -> list[dict]:
    return [
        {
            "row_type": CSV_ROW_VARIABLE,
            "name": "page",
            "display_label": "Page Number",
            "source": "counter",
            "scope": "variable",
            "selector_or_parameter": "page",
            "value_from": "counter",
            "data_type": "integer",
            "start_value": "1",
            "increment": "1",
            "required": "true",
            "multiple_values": "false",
            "unique": "false",
            "include_in_output": "false",
            "sort_order": "1",
            "pagination_mode": "query_parameter",
            "maximum_pages": "100",
            "maximum_records": "500",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_RESULT_SELECTION,
            "name": "scholarship_results",
            "display_label": "Scholarship Results",
            "source": "html_element",
            "scope": "result_page",
            "value_from": "text_content",
            "data_type": "text",
            "required": "true",
            "multiple_values": "true",
            "unique": "false",
            "include_in_output": "false",
            "sort_order": "2",
            "result_selector": ".REPLACE_WITH_VERIFIED_RESULT_SELECTOR",
            "detail_link_selector": ".REPLACE_WITH_VERIFIED_DETAIL_LINK_SELECTOR",
            "follow_detail_page": "true",
            "pagination_mode": "query_parameter",
            "maximum_pages": "100",
            "maximum_records": "500",
            "wait_for_selector": ".REPLACE_WITH_VERIFIED_RESULT_SELECTOR",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_RESULT_FIELD,
            "name": "scholarship_name",
            "display_label": "Scholarship Name",
            "source": "html_element",
            "scope": "result_item",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_TITLE_SELECTOR",
            "value_from": "text_content",
            "data_type": "text",
            "required": "true",
            "transform": "trim|normalize_whitespace",
            "include_in_output": "true",
            "sort_order": "10",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_RESULT_FIELD,
            "name": "detail_url",
            "display_label": "Detail URL",
            "source": "html_attribute",
            "scope": "result_item",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_DETAIL_LINK_SELECTOR",
            "value_from": "attribute",
            "attribute_name": "href",
            "data_type": "url",
            "required": "true",
            "transform": "trim|absolute_url",
            "unique": "true",
            "include_in_output": "true",
            "sort_order": "20",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_RESULT_FIELD,
            "name": "source_page",
            "display_label": "Source Page",
            "source": "current_page_number",
            "scope": "system",
            "value_from": "current_page",
            "data_type": "integer",
            "required": "true",
            "include_in_output": "true",
            "sort_order": "30",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "provider_name",
            "display_label": "Provider Name",
            "source": "html_element",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_PROVIDER_SELECTOR",
            "value_from": "text_content",
            "data_type": "text",
            "transform": "trim|normalize_whitespace",
            "include_in_output": "true",
            "sort_order": "40",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "description",
            "display_label": "Description",
            "source": "html_element",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_DESCRIPTION_SELECTOR",
            "value_from": "text_content",
            "data_type": "long_text",
            "transform": "trim|normalize_whitespace",
            "include_in_output": "true",
            "sort_order": "50",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "scholarship_value",
            "display_label": "Scholarship Value",
            "source": "html_element",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_VALUE_SELECTOR",
            "value_from": "text_content",
            "data_type": "currency",
            "transform": "trim",
            "include_in_output": "true",
            "sort_order": "60",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "study_level",
            "display_label": "Study Level",
            "source": "html_element",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_STUDY_LEVEL_SELECTOR",
            "value_from": "text_content",
            "data_type": "list",
            "multiple_values": "true",
            "transform": "trim|normalize_whitespace",
            "include_in_output": "true",
            "sort_order": "70",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "eligibility",
            "display_label": "Eligibility",
            "source": "html_element",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_ELIGIBILITY_SELECTOR",
            "value_from": "text_content",
            "data_type": "long_text",
            "transform": "trim|normalize_whitespace",
            "include_in_output": "true",
            "sort_order": "80",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "closing_date",
            "display_label": "Closing Date",
            "source": "html_element",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_CLOSING_DATE_SELECTOR",
            "value_from": "text_content",
            "data_type": "date",
            "transform": "trim|parse_date",
            "include_in_output": "true",
            "sort_order": "90",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "application_url",
            "display_label": "Application URL",
            "source": "html_attribute",
            "scope": "detail_page",
            "selector_or_parameter": ".REPLACE_WITH_VERIFIED_APPLICATION_LINK_SELECTOR",
            "value_from": "attribute",
            "attribute_name": "href",
            "data_type": "url",
            "transform": "trim|absolute_url",
            "include_in_output": "true",
            "sort_order": "100",
            "enabled": "true",
        },
        {
            "row_type": CSV_ROW_DETAIL_FIELD,
            "name": "scraped_at",
            "display_label": "Scraped At",
            "source": "run_timestamp",
            "scope": "system",
            "value_from": "timestamp",
            "data_type": "datetime",
            "required": "true",
            "include_in_output": "true",
            "sort_order": "110",
            "enabled": "true",
        },
    ]


def render_csv(rows: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_HEADERS), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _formula_safe(row.get(key, "")) for key in CSV_HEADERS})
    return buffer.getvalue().encode("utf-8-sig")


def template_csv() -> bytes:
    return render_csv(template_rows())


def _parse_list_values(raw: str, row_number: int) -> tuple[Any, list[dict]]:
    if raw in (None, ""):
        return None, []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None, [_issue(row_number, "list_values", raw, "invalid_json", "list_values must be a JSON array.", 'Use ["undergraduate","postgraduate"].')]
    if not isinstance(value, list):
        return None, [_issue(row_number, "list_values", raw, "invalid_json", "list_values must be a JSON array.", 'Use ["undergraduate","postgraduate"].')]
    return value, []


def parse_csv(content: bytes) -> dict:
    max_bytes = getattr(settings, "SCRAPER_CSV_MAX_BYTES", 1_000_000)
    max_rows = getattr(settings, "SCRAPER_CSV_MAX_ROWS", 500)
    if len(content) > max_bytes:
        raise CsvConfigError(f"CSV is larger than {max_bytes} bytes.")
    text = content.decode("utf-8-sig")
    first = text.splitlines()[0] if text.strip() else ""
    headers = next(csv.reader([first])) if first else []
    if len(headers) != len(set(headers)):
        raise CsvConfigError("Duplicate CSV headers are not allowed.")
    missing = [name for name in CSV_HEADERS if name not in headers]
    if missing:
        raise CsvConfigError(f"Missing required headers: {', '.join(missing)}.")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    errors: list[dict] = []
    warnings: list[dict] = []
    seen: dict[tuple[str, str], int] = {}
    for index, raw in enumerate(reader, start=2):
        if index - 1 > max_rows:
            raise CsvConfigError(f"CSV has more than {max_rows} data rows.")
        row_type = (raw.get("row_type") or "").strip().upper()
        name = (raw.get("name") or "").strip()
        enabled = parse_bool(raw.get("enabled"), True)
        row_errors: list[dict] = []
        row_warnings: list[dict] = []
        if row_type not in CSV_ROW_TYPES:
            row_errors.append(_issue(index, "row_type", row_type, "invalid_row_type", "row_type must be VARIABLE, RESULT_SELECTION, RESULT_FIELD or DETAIL_FIELD."))
        key = (row_type, name)
        if name and key in seen:
            row_errors.append(_issue(index, "name", name, "duplicate_row", f"Duplicate {row_type} name already used on row {seen[key]}.", "Names must be unique per row type."))
        elif name:
            seen[key] = index
        list_values, list_errors = _parse_list_values(raw.get("list_values") or "", index)
        row_errors.extend(list_errors)
        try:
            transforms = parse_transforms(raw.get("transform"))
        except ValueError as exc:
            transforms = []
            row_errors.append(_issue(index, "transform", raw.get("transform"), "unknown_transform", str(exc), "Use only names from the safe transform registry."))
        try:
            start_value = parse_int(raw.get("start_value")) if raw.get("start_value") not in (None, "") else None
            increment = parse_int(raw.get("increment")) if raw.get("increment") not in (None, "") else None
            sort_order = parse_int(raw.get("sort_order"), 0)
            maximum_pages = parse_int(raw.get("maximum_pages")) if raw.get("maximum_pages") not in (None, "") else None
            maximum_records = parse_int(raw.get("maximum_records")) if raw.get("maximum_records") not in (None, "") else None
        except ValueError as exc:
            start_value = increment = sort_order = maximum_pages = maximum_records = None
            row_errors.append(_issue(index, "start_value", raw.get("start_value"), "invalid_integer", str(exc)))
        payload = {**raw, "list_values": list_values, "transform": "|".join(transforms) if transforms else raw.get("transform")}
        canonical = None
        if row_type == CSV_ROW_VARIABLE:
            try:
                canonical = normalize_variable(payload, via=ORIGIN_CSV)
                more_errors, more_warnings = validate_variable_item(canonical, row=index)
                row_errors.extend(more_errors)
                row_warnings.extend(more_warnings)
            except ValueError as exc:
                canonical = None
                row_errors.append(_issue(index, "source", raw.get("source"), "invalid_variable", str(exc)))
        elif row_type in {CSV_ROW_RESULT_FIELD, CSV_ROW_DETAIL_FIELD}:
            try:
                canonical = normalize_field(payload, via=ORIGIN_CSV, row_type=row_type)
                more_errors, more_warnings = validate_field_item(canonical, row=index)
                row_errors.extend(more_errors)
                row_warnings.extend(more_warnings)
            except ValueError as exc:
                canonical = None
                row_errors.append(_issue(index, "source", raw.get("source"), "invalid_field", str(exc)))
        elif row_type == CSV_ROW_RESULT_SELECTION:
            try:
                canonical = normalize_result_selection(payload)
                more_errors, more_warnings = validate_result_selection(canonical, row=index)
                row_errors.extend(more_errors)
                row_warnings.extend(more_warnings)
            except ValueError as exc:
                canonical = None
                row_errors.append(_issue(index, "maximum_pages", raw.get("maximum_pages"), "invalid_integer", str(exc)))
        errors.extend(row_errors)
        warnings.extend(row_warnings)
        rows.append(
            {
                "csv_row": index,
                "row_type": row_type,
                "name": name,
                "display_label": (raw.get("display_label") or "").strip(),
                "source": (raw.get("source") or "").strip(),
                "selector": (raw.get("selector_or_parameter") or raw.get("result_selector") or "").strip(),
                "data_type": (raw.get("data_type") or "").strip(),
                "enabled": enabled,
                "raw": raw,
                "canonical": canonical,
                "errors": row_errors,
                "warnings": row_warnings,
                "valid": not row_errors,
                "start_value": start_value,
                "increment": increment,
                "sort_order": sort_order,
                "maximum_pages": maximum_pages,
                "maximum_records": maximum_records,
            }
        )
    return {"rows": rows, "errors": errors, "warnings": warnings, "headers": headers}


def _existing_index(job: ScrapeJob) -> dict[tuple[str, str], Any]:
    index: dict[tuple[str, str], Any] = {}
    for item in job.variables.all():
        index[(CSV_ROW_VARIABLE, item.name)] = item
    for item in job.fields.all():
        row_type = CSV_ROW_DETAIL_FIELD if item.scope == "detail_page" else CSV_ROW_RESULT_FIELD
        index[(row_type, item.name)] = item
    if job.result_selector or job.detail_link_selector:
        index[(CSV_ROW_RESULT_SELECTION, (job.origin_meta or {}).get("result_selection_name") or "results")] = job
    return index


def _same_variable(model: VariableParameter, canonical: dict) -> bool:
    return (
        model.label == canonical["label"]
        and model.source_type == canonical["source_type"]
        and model.selector == canonical["selector"]
        and model.data_type == canonical["data_type"]
        and (model.configuration or {}) == (canonical.get("configuration") or {})
        and list(model.transformations or []) == list(canonical.get("transformations") or [])
        and model.required == canonical["required"]
        and model.multiple == canonical["multiple"]
    )


def _same_field(model: ScrapeField, canonical: dict) -> bool:
    return (
        model.label == canonical["label"]
        and model.scope == canonical["scope"]
        and model.selector == canonical["selector"]
        and model.extraction_method == canonical["extraction_method"]
        and model.attribute_name == canonical["attribute_name"]
        and model.data_type == canonical["data_type"]
        and list(model.transformations or []) == list(canonical.get("transformations") or [])
        and model.required == canonical["required"]
        and model.unique == canonical["unique"]
        and model.include_in_csv == canonical["include_in_csv"]
    )


def preview_import(job: ScrapeJob, content: bytes, *, mode: str = "merge") -> dict:
    parsed = parse_csv(content)
    mode = "replace" if mode == "replace" else "merge"
    existing = _existing_index(job)
    csv_keys = set()
    new = updated = unchanged = conflicts = 0
    preview_rows = []
    for row in parsed["rows"]:
        key = (row["row_type"], row["name"])
        csv_keys.add(key)
        match = existing.get(key)
        if row["row_type"] == CSV_ROW_RESULT_SELECTION:
            match = job if (job.result_selector or job.detail_link_selector) else None
        action = "create"
        if not row["enabled"]:
            action = "skip"
        elif not row["valid"]:
            action = "reject"
        elif match is None:
            action = "create"
            new += 1
        elif row["row_type"] == CSV_ROW_VARIABLE and _same_variable(match, row["canonical"] or {}):
            action = "unchanged"
            unchanged += 1
        elif row["row_type"] in {CSV_ROW_RESULT_FIELD, CSV_ROW_DETAIL_FIELD} and _same_field(match, row["canonical"] or {}):
            action = "unchanged"
            unchanged += 1
        elif row["row_type"] == CSV_ROW_RESULT_SELECTION and match is not None:
            canonical = row["canonical"] or {}
            if job.result_selector == canonical.get("result_selector") and job.detail_link_selector == canonical.get("detail_link_selector"):
                action = "unchanged"
                unchanged += 1
            else:
                action = "update"
                updated += 1
        else:
            action = "update"
            updated += 1
        if action == "update" and match is not None and getattr(match, "created_via", ORIGIN_MANUAL) == ORIGIN_MANUAL:
            conflicts += 1
        row["action"] = action
        preview_rows.append(row)
    kept = 0
    deleted = 0
    kept_rows = []
    deleted_rows = []
    for key, obj in existing.items():
        if key in csv_keys:
            continue
        if mode == "merge":
            kept += 1
            kept_rows.append({"row_type": key[0], "name": key[1], "origin": getattr(obj, "created_via", ORIGIN_MANUAL)})
        else:
            deleted += 1
            deleted_rows.append({"row_type": key[0], "name": key[1], "origin": getattr(obj, "created_via", ORIGIN_MANUAL)})
    valid = sum(1 for row in preview_rows if row["valid"])
    invalid = sum(1 for row in preview_rows if not row["valid"])
    warning_rows = sum(1 for row in preview_rows if row["warnings"])
    return {
        "mode": mode,
        "rows": preview_rows,
        "errors": parsed["errors"],
        "warnings": parsed["warnings"],
        "summary": {
            "total_rows": len(preview_rows),
            "valid_rows": valid,
            "warning_rows": warning_rows,
            "invalid_rows": invalid,
            "new_rows": new,
            "updated_rows": updated,
            "unchanged_rows": unchanged,
            "conflicting_rows": conflicts,
            "kept_rows": kept,
            "deleted_rows": deleted,
        },
        "kept_rows": kept_rows,
        "deleted_rows": deleted_rows,
        "can_import": invalid == 0 and all(row["valid"] or not row["enabled"] for row in preview_rows),
        "error_csv": errors_csv(parsed["errors"]),
    }


def errors_csv(errors: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["row", "column", "value", "code", "message", "suggestion"], lineterminator="\n")
    writer.writeheader()
    for item in errors:
        writer.writerow({key: _formula_safe(item.get(key, "")) for key in writer.fieldnames})
    return buffer.getvalue()


@transaction.atomic
def apply_import(job: ScrapeJob, content: bytes, *, mode: str = "merge", confirm_replace: bool = False, user=None) -> dict:
    preview = preview_import(job, content, mode=mode)
    if mode == "replace" and not confirm_replace:
        raise CsvConfigError("Replace requires explicit confirmation.", [_issue(0, "mode", "replace", "replace_unconfirmed", "Select Replace existing configuration to continue.")])
    if not preview["can_import"]:
        raise CsvConfigError("The CSV has validation errors and was not imported.", preview["errors"])
    if mode == "replace":
        job.variables.all().delete()
        job.fields.all().delete()
        apply_result_selection(
            job,
            {
                "result_selector": "",
                "detail_link_selector": "",
                "follow_detail_pages": False,
                "maximum_pages": job.maximum_pages,
                "maximum_records": job.maximum_records,
            },
            via=ORIGIN_CSV,
        )
    for row in preview["rows"]:
        if not row["enabled"] or not row["valid"]:
            continue
        if mode == "merge" and row["action"] in {"skip", "unchanged"}:
            continue
        canonical = row["canonical"]
        if row["row_type"] == CSV_ROW_VARIABLE:
            save_variable(job, canonical, via=ORIGIN_CSV)
        elif row["row_type"] in {CSV_ROW_RESULT_FIELD, CSV_ROW_DETAIL_FIELD}:
            save_field(job, canonical, via=ORIGIN_CSV)
            if canonical.get("unique"):
                job.unique_field_name = canonical["name"]
        elif row["row_type"] == CSV_ROW_RESULT_SELECTION:
            apply_result_selection(job, canonical, via=ORIGIN_CSV)
            meta = dict(job.origin_meta or {})
            meta["result_selection_name"] = canonical.get("name") or "results"
            job.origin_meta = meta
    job.updated_by = user or job.updated_by
    job.version += 1
    job.save()
    return {"job": snapshot_job(job), "summary": preview["summary"]}


def export_job_csv(job: ScrapeJob) -> bytes:
    rows = []
    pagination = job.pagination_settings or {}
    request = job.request_settings or {}
    origin = (job.origin_meta or {}).get("result_selection") or {}
    if job.result_selector or job.detail_link_selector:
        rows.append(
            {
                "row_type": CSV_ROW_RESULT_SELECTION,
                "name": (job.origin_meta or {}).get("result_selection_name") or "results",
                "display_label": "Result selection",
                "source": "html_element",
                "scope": "result_page",
                "result_selector": job.result_selector,
                "detail_link_selector": job.detail_link_selector,
                "follow_detail_page": "true" if job.follow_detail_pages else "false",
                "pagination_mode": pagination.get("mode") or "query_parameter",
                "maximum_pages": job.maximum_pages or pagination.get("maximum_pages") or "",
                "maximum_records": job.maximum_records or "",
                "wait_for_selector": request.get("wait_for_selector") or "",
                "enabled": "true",
            }
        )
    for item in job.variables.all():
        config = item.configuration or {}
        rows.append(
            {
                "row_type": CSV_ROW_VARIABLE,
                "name": item.name,
                "display_label": item.label,
                "source": item.source_type,
                "scope": item.scope,
                "selector_or_parameter": item.selector or config.get("parameter") or "",
                "value_from": item.value_from,
                "attribute_name": item.attribute_name,
                "data_type": item.data_type,
                "start_value": config.get("start_value", ""),
                "increment": config.get("increment", ""),
                "fixed_value": config.get("fixed_value", ""),
                "list_values": json.dumps(config["list_values"]) if config.get("list_values") is not None else "",
                "default_value": "" if item.default_value is None else item.default_value,
                "required": "true" if item.required else "false",
                "multiple_values": "true" if item.multiple else "false",
                "transform": "|".join(step if isinstance(step, str) else step.get("name", "") for step in (item.transformations or [])),
                "unique": "true" if item.unique else "false",
                "include_in_output": "false",
                "sort_order": item.sort_order,
                "enabled": "true",
            }
        )
    for item in job.fields.all():
        row_type = CSV_ROW_DETAIL_FIELD if item.scope == "detail_page" else CSV_ROW_RESULT_FIELD
        source = "system" if item.scope == "system" else ("html_attribute" if item.extraction_method == "attribute" else "html_element")
        rows.append(
            {
                "row_type": row_type,
                "name": item.name,
                "display_label": item.label,
                "source": source,
                "scope": item.scope,
                "selector_or_parameter": item.selector,
                "value_from": item.extraction_method,
                "attribute_name": item.attribute_name,
                "data_type": item.data_type,
                "default_value": "" if item.default_value is None else item.default_value,
                "required": "true" if item.required else "false",
                "multiple_values": "true" if item.multiple else "false",
                "transform": "|".join(step if isinstance(step, str) else step.get("name", "") for step in (item.transformations or [])),
                "unique": "true" if item.unique else "false",
                "include_in_output": "true" if item.include_in_csv else "false",
                "sort_order": item.sort_order,
                "enabled": "true",
            }
        )
    _ = origin
    return render_csv(rows)


def preview_counter(job: ScrapeJob, variable: Mapping[str, Any], count: int = 3) -> dict:
    config = variable.get("configuration") or {}
    start = int(config.get("start_value") or config.get("start") or 1)
    increment = int(config.get("increment") or 1)
    name = variable.get("name") or "page"
    values = [start + increment * index for index in range(count)]
    template = variable.get("url_template") or job.url_template or ""
    urls = []
    if template:
        for value in values:
            try:
                urls.append(render(template, {name: value}))
            except Exception as exc:
                return {"ok": False, "error": str(exc), "values": values, "rendered_urls": []}
    return {"ok": True, "values": values, "rendered_urls": urls, "placeholder": False}
