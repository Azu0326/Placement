from django.apps import AppConfig


class ScraperConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scraper"
    verbose_name = "Scraper"

    def ready(self):
        from . import checks  # noqa: F401
        from .services.queue import maybe_start_inline_worker

        maybe_start_inline_worker()
