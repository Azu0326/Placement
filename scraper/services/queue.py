"""Database-backed scrape queue.

Runs are claimed via a status update so multiple workers cannot execute the same
run. Two dispatch routes call the same ``execute_run``:

* Default: a lightweight thread inside the web process (``enqueue`` spawns a
  thread; ``maybe_start_inline_worker`` polls for queued work under
  ``runserver`` / ``runscraper``).
* When ``SCRAPER_USE_CELERY`` is enabled: the run is handed to the Celery task
  in ``scraper.tasks`` and executed by a separate ``celery -A config worker``
  process. This is the more reliable route under gunicorn, where the in-process
  polling thread does not start.

Tests call ``process_one`` / ``execute_run`` directly.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from django.conf import settings

from scraper.constants import RUN_QUEUED
from scraper.models import ScrapeRun

from .orchestrator import execute_run

logger = logging.getLogger("scrapos.scraper")

_WORKER_STARTED = False
_LOCK = threading.Lock()


def enqueue(run: ScrapeRun) -> ScrapeRun:
    if run.status != RUN_QUEUED:
        run.status = RUN_QUEUED
        run.save(update_fields=["status"])
    if getattr(settings, "TESTING", False):
        return run
    if getattr(settings, "SCRAPER_USE_CELERY", False):
        # Hand the run to a Celery worker. Imported here so that when Celery is
        # disabled the module (and the celery dependency) is never required.
        from scraper.tasks import execute_run_task

        execute_run_task.delay(str(run.id))
        logger.info("scraper_run_dispatched_celery run_id=%s", run.id)
        return run
    thread = threading.Thread(target=_safe_execute, args=(str(run.id),), daemon=True, name=f"scrape-run-{run.id}")
    thread.start()
    return run


def _safe_execute(run_id: str) -> None:
    try:
        execute_run(run_id)
    except Exception:
        logger.exception("scraper_run_failed run_id=%s", run_id)


def process_one() -> bool:
    run = (
        ScrapeRun.objects.filter(status=RUN_QUEUED)
        .order_by("created_at")
        .first()
    )
    if run is None:
        return False
    execute_run(run.id)
    return True


def _poll_loop() -> None:
    from django.db import close_old_connections

    interval = float(getattr(settings, "SCRAPER_WORKER_POLL_SECONDS", 2))
    while True:
        try:
            close_old_connections()
            process_one()
        except Exception:
            logger.exception("scraper_worker_poll_failed")
        finally:
            close_old_connections()
        time.sleep(interval)


def maybe_start_inline_worker() -> None:
    global _WORKER_STARTED
    if getattr(settings, "TESTING", False):
        return
    # When Celery owns dispatch, the in-process polling thread is unnecessary.
    if getattr(settings, "SCRAPER_USE_CELERY", False):
        return
    if not getattr(settings, "SCRAPER_INLINE_WORKER", True):
        return
    argv = sys.argv[1:2]
    if not argv or argv[0] not in {"runserver", "runscraper"}:
        return
    # Avoid starting a thread for the Django autoreload parent.
    if argv and argv[0] == "runserver" and os.environ.get("RUN_MAIN") != "true":
        return
    with _LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
        threading.Thread(target=_poll_loop, daemon=True, name="scrapos-scraper-worker").start()
        logger.info("scraper_inline_worker_started")
