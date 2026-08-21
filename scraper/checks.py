"""Deployment checks for scraper configuration."""

from django.conf import settings
from django.core.checks import Warning, register


@register()
def scraper_export_directory_writable(app_configs, **kwargs):
    from pathlib import Path

    path = Path(getattr(settings, "SCRAPER_EXPORT_DIRECTORY", ""))
    if not path:
        return []
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [
            Warning(
                f"SCRAPER_EXPORT_DIRECTORY cannot be created: {exc}",
                id="scraper.W001",
            )
        ]
    return []
