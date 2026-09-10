"""Ensure the Celery app is loaded when Django starts.

Importing the Celery app here means shared tasks are registered and the app is
available wherever Django is imported (web process and Celery worker alike).
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
