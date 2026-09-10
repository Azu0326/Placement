"""Run a scrape job from a frozen configuration snapshot."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone as dj_timezone

from scraper.constants import (
    ACTIVE_RUN_STATUSES,
    DUPLICATE_KEEP,
    DUPLICATE_SKIP,
    DUPLICATE_UPDATE,
    PHASE_DETAIL,
    PHASE_FINALISING,
    PHASE_LISTING,
    PHASE_PREPARING,
    RECORD_FAILED,
    RECORD_INVALID,
    RECORD_PARTIAL,
    RECORD_VALID,
    RUN_CANCELLED,
    RUN_CANCELLING,
    RUN_COMPLETED,
    RUN_COMPLETED_WITH_ERRORS,
    RUN_FAILED,
    RUN_PAUSED,
    RUN_PAUSING,
    RUN_PREPARING,
    RUN_QUEUED,
    RUN_RUNNING,
    SCOPE_DETAIL_PAGE,
    SCOPE_RESULT_ITEM,
    SCOPE_RESULT_PAGE,
    SCOPE_SYSTEM,
    SCOPE_VARIABLE,
    SOURCE_COUNTER,
    STOP_USER_CANCEL,
    VALUE_ATTRIBUTE,
)
from scraper.models import ScrapedRecord, ScrapeRun

from . import events
from .fetcher import fetch_page
from .html_parser import extract, page_fingerprint, parse_html, select
from .http_fetcher import FetchError
from .pagination import PaginationState, next_listing_url, should_stop
from .ssrf import RequestPolicyError
from .transforms import apply_pipeline
from .types import TypeError_, normalize
from .url_template import render
from .variables import resolve_variable


class RunCancelled(Exception):
    pass


class RunPaused(Exception):
    pass


def _refresh(run: ScrapeRun) -> ScrapeRun:
    run.refresh_from_db(fields=["status", "cancelled_at"])
    return run


def _check_control(run: ScrapeRun) -> None:
    _refresh(run)
    if run.status == RUN_CANCELLING:
        raise RunCancelled()
    if run.status == RUN_PAUSING:
        raise RunPaused()


def _delay(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(min(float(seconds), 10))


def _extract_field(spec: dict, html: str, *, base_url: str) -> Any:
    if spec.get("scope") in {SCOPE_SYSTEM, SCOPE_VARIABLE} and not spec.get("selector"):
        return spec.get("default_value")
    result = extract(
        html,
        spec.get("selector") or "",
        value_from=spec.get("extraction_method") or spec.get("value_from") or "text_content",
        attribute_name=spec.get("attribute_name") or "",
        multiple=bool(spec.get("multiple")),
        base_url=base_url,
    )
    if result.error:
        raise ValueError(result.error)
    raw = result.values if spec.get("multiple") else (result.values[0] if result.values else None)
    return apply_pipeline(raw, spec.get("transformations") or [], base_url=base_url)


def _resolve_counters(snapshot: dict, page: int) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for spec in snapshot.get("variables") or []:
        if spec.get("source_type") in {SOURCE_COUNTER, "page_number"}:
            values[spec["name"]] = resolve_variable(spec, page_number=page)
    return values


def _listing_url(snapshot: dict, page: int, variables: dict[str, Any]) -> str:
    template = snapshot.get("url_template") or (snapshot.get("pagination_settings") or {}).get("url_template")
    if template:
        values = dict(variables)
        values.setdefault("page", page)
        return render(template, values)
    return snapshot["start_url"]


def execute_run(run_id) -> ScrapeRun:
    run = ScrapeRun.objects.select_related("job").get(pk=run_id)
    claimed = ScrapeRun.objects.filter(pk=run.pk, status__in={RUN_QUEUED, RUN_PREPARING}).update(
        status=RUN_RUNNING,
        current_phase=PHASE_PREPARING,
        started_at=dj_timezone.now(),
    )
    if not claimed and run.status not in {RUN_QUEUED, RUN_PREPARING, RUN_RUNNING}:
        return run
    run.refresh_from_db()
    snapshot = run.snapshot or {}
    events.emit(run, "run_started", "Run started.", job_id=str(run.job_id))
    started = time.monotonic()
    max_runtime = int(
        (snapshot.get("execution_settings") or {}).get("max_run_seconds")
        or getattr(settings, "SCRAPER_MAX_RUN_SECONDS", 900)
    )
    try:
        _run_listing(run, snapshot, started, max_runtime)
        if snapshot.get("follow_detail_pages"):
            _run_details(run, snapshot, started, max_runtime)
        _finalize(run)
    except RunCancelled:
        run.status = RUN_CANCELLED
        run.cancelled_at = dj_timezone.now()
        run.finished_at = dj_timezone.now()
        run.current_phase = ""
        run.save(update_fields=["status", "cancelled_at", "finished_at", "current_phase"])
        events.warn(run, "cancelled", "Run cancelled.")
    except RunPaused:
        run.status = RUN_PAUSED
        run.finished_at = dj_timezone.now()
        run.save(update_fields=["status", "finished_at"])
        events.warn(run, "paused", "Run paused.")
    except Exception as exc:
        run.status = RUN_FAILED
        run.error_summary = str(exc)[:500]
        run.finished_at = dj_timezone.now()
        run.save(update_fields=["status", "error_summary", "finished_at"])
        events.error(run, "failed", str(exc)[:500])
        raise
    return run


def _run_listing(run: ScrapeRun, snapshot: dict, started: float, max_runtime: int) -> None:
    run.current_phase = PHASE_LISTING
    run.save(update_fields=["current_phase"])
    pagination = snapshot.get("pagination_settings") or {}
    execution = snapshot.get("execution_settings") or {}
    request = snapshot.get("request_settings") or {}
    max_pages = int(snapshot.get("maximum_pages") or pagination.get("maximum_pages") or getattr(settings, "SCRAPER_MAX_PAGES", 100))
    max_records = int(snapshot.get("maximum_records") or getattr(settings, "SCRAPER_MAX_RECORDS", 5000))
    delay = float(execution.get("delay_seconds") or getattr(settings, "SCRAPER_DEFAULT_DELAY_SECONDS", 0.5))
    state = PaginationState(page=0, url=snapshot.get("start_url") or "")
    page = int((pagination.get("start") or 1))
    consecutive_empty = 0

    while True:
        _check_control(run)
        if time.monotonic() - started > max_runtime:
            state.stop_reason = "maximum_runtime_reached"
            break
        variables = _resolve_counters(snapshot, page)
        try:
            url = _listing_url(snapshot, page, variables)
        except Exception as exc:
            events.error(run, "url_error", str(exc), page=page)
            break
        run.current_page = page
        run.pages_attempted += 1
        run.save(update_fields=["current_page", "pages_attempted"])
        events.emit(run, "fetch_listing", "Fetching listing page.", page=page, url=_redact(url))
        try:
            fetched = fetch_page(
                url,
                rendering_mode=snapshot.get("rendering_mode") or "auto",
                method=snapshot.get("http_method") or "GET",
                timeout=request.get("timeout"),
                wait_after_load_ms=int(request.get("wait_after_load_ms") or 0),
                wait_for_selector=request.get("wait_for_selector") or snapshot.get("result_selector") or "",
                user_agent=request.get("user_agent") or "",
                headers=request.get("headers") or {},
                follow_redirects=request.get("follow_redirects", True),
                verify_tls=request.get("verify_tls", True),
            )
        except (FetchError, RequestPolicyError) as exc:
            state.failures += 1
            events.error(run, "fetch_failed", str(exc), page=page, url=_redact(url))
            if should_stop(
                pagination,
                state,
                result_count=0,
                new_unique=0,
                new_details=0,
                next_url=None,
                next_disabled=False,
                fingerprint="",
                cancelled=False,
                runtime_exceeded=False,
                records_created=run.records_created,
                max_pages=max_pages,
                max_records=max_records,
            ):
                break
            page += int(pagination.get("increment") or 1)
            continue

        _check_control(run)
        items_html = _result_items(fetched.html, snapshot)
        identifiers = []
        new_unique = 0
        new_details = 0
        if not items_html:
            consecutive_empty += 1
        else:
            consecutive_empty = 0
        for item_html in items_html:
            if run.records_created >= max_records:
                break
            _check_control(run)
            record, created, detail = _persist_item(run, snapshot, item_html, fetched.final_url, page)
            if detail:
                identifiers.append(detail)
                if detail not in state.detail_urls:
                    state.detail_urls.add(detail)
                    new_details += 1
                    run.detail_pages_queued += 1
            key = record.unique_key if record else ""
            if key and key not in state.unique_keys:
                state.unique_keys.add(key)
                new_unique += 1
            elif created:
                new_unique += 1
        run.pages_completed += 1
        run.records_discovered += len(items_html)
        run.save(
            update_fields=[
                "pages_completed",
                "records_discovered",
                "records_created",
                "records_skipped",
                "records_failed",
                "detail_pages_queued",
            ]
        )
        fingerprint = page_fingerprint(fetched.html, identifiers)
        next_url = next_listing_url(
            pagination,
            PaginationState(page=page, url=fetched.final_url),
            html=fetched.html,
            variables=variables,
        )
        state.empty_pages = consecutive_empty
        reason = should_stop(
            pagination,
            state,
            result_count=len(items_html),
            new_unique=new_unique,
            new_details=new_details,
            next_url=next_url,
            next_disabled=False,
            fingerprint=fingerprint,
            cancelled=False,
            runtime_exceeded=time.monotonic() - started > max_runtime,
            records_created=run.records_created,
            max_pages=max_pages,
            max_records=max_records,
        )
        state.fingerprints.append(fingerprint)
        if next_url:
            state.next_urls.append(next_url)
        state.page = page
        if reason:
            events.emit(run, "stop", f"Stopped: {reason}.", reason=reason, page=page)
            break
        page += int(pagination.get("increment") or 1)
        _delay(delay)


def _result_items(html: str, snapshot: dict) -> list[str]:
    selector = snapshot.get("result_selector") or ""
    if not selector:
        return [html]
    soup = parse_html(html)
    try:
        matches = select(soup, selector)
    except Exception:
        return []
    return [str(item) for item in matches]


def _persist_item(run: ScrapeRun, snapshot: dict, item_html: str, source_url: str, page: int):
    now = datetime.now(timezone.utc)
    raw: dict[str, Any] = {}
    normalized: dict[str, Any] = {}
    errors: list[str] = []
    for spec in snapshot.get("fields") or []:
        if spec.get("scope") not in {SCOPE_RESULT_ITEM, SCOPE_RESULT_PAGE, SCOPE_VARIABLE, SCOPE_SYSTEM, ""}:
            continue
        try:
            if spec["name"] == "source_page":
                value = page
            elif spec["name"] == "source_url":
                value = source_url
            elif spec["name"] == "scraped_at":
                value = now.isoformat()
            elif spec.get("scope") == SCOPE_SYSTEM and spec["name"] in {"source_page", "source_url", "scraped_at"}:
                value = {"source_page": page, "source_url": source_url, "scraped_at": now.isoformat()}[spec["name"]]
            else:
                value = _extract_field(spec, item_html, base_url=source_url)
            raw[spec["name"]] = value
            normalized[spec["name"]] = normalize(value, spec.get("data_type") or "text", multiple=bool(spec.get("multiple")))
        except (ValueError, TypeError_) as exc:
            errors.append(f"{spec['name']}: {exc}")
            if spec.get("default_value") not in (None, ""):
                normalized[spec["name"]] = spec["default_value"]
            elif spec.get("required"):
                run.records_failed += 1
    detail = ""
    if snapshot.get("detail_link_selector"):
        extracted = extract(
            item_html,
            snapshot["detail_link_selector"],
            value_from=VALUE_ATTRIBUTE,
            attribute_name=snapshot.get("detail_link_attribute") or "href",
            base_url=source_url,
        )
        if extracted.values:
            detail = str(extracted.values[0])
            raw.setdefault("detail_url", detail)
            normalized.setdefault("detail_url", detail)
    unique_name = snapshot.get("unique_field_name") or ""
    unique_key = ""
    if unique_name:
        unique_key = str(normalized.get(unique_name) or raw.get(unique_name) or "")
    fingerprint = hashlib.sha256(repr(sorted(normalized.items())).encode()).hexdigest()
    existing = None
    if unique_key:
        existing = ScrapedRecord.objects.filter(run=run, unique_key=unique_key).first()
    handling = snapshot.get("duplicate_handling") or DUPLICATE_SKIP
    if existing and handling == DUPLICATE_SKIP:
        run.records_skipped += 1
        return existing, False, detail
    status = RECORD_VALID
    if errors and any(spec.get("required") and spec["name"] in {err.split(":")[0] for err in errors} for spec in snapshot.get("fields") or []):
        status = RECORD_INVALID
    elif errors:
        status = RECORD_PARTIAL
    payload = {
        "job": run.job,
        "source_url": source_url,
        "source_page": page,
        "detail_url": detail,
        "raw_data": raw,
        "normalized_data": normalized,
        "validation_errors": errors,
        "content_fingerprint": fingerprint,
        "status": status,
        "unique_key": unique_key,
    }
    if existing and handling == DUPLICATE_UPDATE:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.save()
        return existing, False, detail
    sequence = (run.records.order_by("-sequence_number").values_list("sequence_number", flat=True).first() or 0) + 1
    record = ScrapedRecord.objects.create(run=run, sequence_number=sequence, **payload)
    run.records_created += 1
    return record, True, detail


def _run_details(run: ScrapeRun, snapshot: dict, started: float, max_runtime: int) -> None:
    run.current_phase = PHASE_DETAIL
    run.save(update_fields=["current_phase"])
    request = snapshot.get("request_settings") or {}
    execution = snapshot.get("execution_settings") or {}
    delay = float(execution.get("delay_seconds") or getattr(settings, "SCRAPER_DEFAULT_DELAY_SECONDS", 0.5))
    detail_fields = [item for item in snapshot.get("fields") or [] if item.get("scope") == SCOPE_DETAIL_PAGE]
    if not detail_fields:
        return
    qs = run.records.exclude(detail_url="").order_by("sequence_number")
    seen: set[str] = set()
    for record in qs.iterator(chunk_size=50):
        _check_control(run)
        if time.monotonic() - started > max_runtime:
            events.warn(run, "runtime", "Stopped detail phase at the runtime limit.")
            return
        if record.detail_url in seen:
            continue
        seen.add(record.detail_url)
        events.emit(run, "fetch_detail", "Fetching detail page.", url=_redact(record.detail_url))
        try:
            fetched = fetch_page(
                record.detail_url,
                rendering_mode=snapshot.get("rendering_mode") or "auto",
                timeout=request.get("timeout"),
                wait_after_load_ms=int(request.get("wait_after_load_ms") or 0),
                user_agent=request.get("user_agent") or "",
                headers=request.get("headers") or {},
                follow_redirects=request.get("follow_redirects", True),
                verify_tls=request.get("verify_tls", True),
            )
        except (FetchError, RequestPolicyError) as exc:
            record.status = RECORD_FAILED
            record.validation_errors = list(record.validation_errors or []) + [str(exc)]
            record.save(update_fields=["status", "validation_errors"])
            run.records_failed += 1
            continue
        raw = dict(record.raw_data or {})
        normalized = dict(record.normalized_data or {})
        errors = list(record.validation_errors or [])
        for spec in detail_fields:
            try:
                value = _extract_field(spec, fetched.html, base_url=fetched.final_url)
                raw[spec["name"]] = value
                normalized[spec["name"]] = normalize(value, spec.get("data_type") or "text", multiple=bool(spec.get("multiple")))
            except (ValueError, TypeError_) as exc:
                errors.append(f"{spec['name']}: {exc}")
        record.raw_data = raw
        record.normalized_data = normalized
        record.validation_errors = errors
        record.status = RECORD_INVALID if errors and any(f.get("required") for f in detail_fields) else record.status
        record.save()
        run.detail_pages_completed += 1
        run.save(update_fields=["detail_pages_completed", "records_failed"])
        _delay(delay)


def _finalize(run: ScrapeRun) -> None:
    run.current_phase = PHASE_FINALISING
    if run.records_failed:
        run.status = RUN_COMPLETED_WITH_ERRORS
    else:
        run.status = RUN_COMPLETED
    run.finished_at = dj_timezone.now()
    run.job.last_run_at = run.finished_at
    run.job.save(update_fields=["last_run_at"])
    run.save(update_fields=["current_phase", "status", "finished_at", "records_created", "records_failed", "records_skipped"])
    events.emit(run, "completed", "Run finished.", records=run.records_created)


def _redact(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(part in key.lower() for part in ("token", "key", "secret", "password", "auth")):
            pairs.append((key, "REDACTED"))
        else:
            pairs.append((key, value))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(pairs), ""))


def request_cancel(run: ScrapeRun) -> ScrapeRun:
    if run.status in {RUN_QUEUED}:
        run.status = RUN_CANCELLED
        run.cancelled_at = dj_timezone.now()
        run.finished_at = run.cancelled_at
        run.save(update_fields=["status", "cancelled_at", "finished_at"])
        return run
    if run.status in ACTIVE_RUN_STATUSES:
        run.status = RUN_CANCELLING
        run.save(update_fields=["status"])
    return run


def request_pause(run: ScrapeRun) -> ScrapeRun:
    if run.status in ACTIVE_RUN_STATUSES:
        run.status = RUN_PAUSING
        run.save(update_fields=["status"])
    return run
