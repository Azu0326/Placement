"""Celery tasks for the scraper.

The task is intentionally thin: it calls ``execute_run`` and nothing else. All
extraction logic stays in ``services/orchestrator.py`` — moving a run onto a
Celery worker changes *where* it runs, not *how*. This mirrors the in-process
path in ``services/queue.py`` so both dispatch routes call the same function.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("scrapos.scraper")


@shared_task(name="scraper.execute_run", bind=True, acks_late=True)
def execute_run_task(self, run_id: str) -> None:
    # Imported inside the task so importing this module never pulls in the
    # orchestrator (and its dependencies) at Celery startup / autodiscovery.
    from .services.orchestrator import execute_run

    logger.info("scraper_celery_run_started run_id=%s", run_id)
    execute_run(run_id)
    logger.info("scraper_celery_run_finished run_id=%s", run_id)
