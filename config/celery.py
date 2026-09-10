"""Celery application for Scrapos.

Celery is an optional dispatcher for scrape runs. When ``SCRAPER_USE_CELERY`` is
enabled, ``scraper.services.queue.enqueue`` hands the run to the Celery task in
``scraper.tasks`` instead of the in-process thread. The task itself only calls
``execute_run`` — the orchestrator and extraction engine are unchanged.

The worker is started with:

    celery -A config worker --loglevel=info

Configuration is read from Django settings using the ``CELERY_`` prefix (see
``config/settings.py``); the broker is Redis.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("scrapos")

# All Celery settings live in Django settings under the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Discover tasks.py in each installed app (e.g. scraper/tasks.py).
app.autodiscover_tasks()
