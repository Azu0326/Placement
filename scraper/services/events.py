"""Structured run events. Never store secrets or full HTML."""

from __future__ import annotations

import logging
from typing import Any

from scraper.constants import EVENT_ERROR, EVENT_INFO, EVENT_WARNING, SENSITIVE_HEADER_NAMES
from scraper.models import ScrapeEvent, ScrapeRun

logger = logging.getLogger("scrapos.scraper")


def _clean_context(context: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = {}
    for key, value in (context or {}).items():
        if key.lower() in SENSITIVE_HEADER_NAMES or any(part in key.lower() for part in ("cookie", "token", "password", "secret", "authorization")):
            continue
        if key in {"html", "body", "content"}:
            continue
        cleaned[key] = value
    return cleaned


def emit(run: ScrapeRun, event_type: str, message: str, *, level: str = EVENT_INFO, **context) -> ScrapeEvent:
    event = ScrapeEvent.objects.create(
        run=run,
        level=level,
        event_type=event_type,
        message=message[:500],
        context=_clean_context(context),
    )
    logger.info(
        "scraper_event run_id=%s job_id=%s type=%s page=%s %s",
        run.id,
        run.job_id,
        event_type,
        context.get("page"),
        message,
    )
    return event


def warn(run: ScrapeRun, event_type: str, message: str, **context) -> ScrapeEvent:
    return emit(run, event_type, message, level=EVENT_WARNING, **context)


def error(run: ScrapeRun, event_type: str, message: str, **context) -> ScrapeEvent:
    return emit(run, event_type, message, level=EVENT_ERROR, **context)
