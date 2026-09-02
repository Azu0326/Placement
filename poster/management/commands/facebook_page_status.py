"""Show whether Facebook Page publishing is configured, without leaking tokens.

    python manage.py facebook_page_status
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from poster.conf import get_facebook_config
from poster.exceptions import FacebookNotConfigured, FacebookPublishError
from poster.services.facebook_service import FacebookPageService


class Command(BaseCommand):
    help = "Check Facebook Page publishing configuration (never prints tokens)."

    def handle(self, *args, **options):
        config = get_facebook_config()
        self.stdout.write(f"graph_api_version: {config.graph_api_version}")
        self.stdout.write(f"app_id_configured: {bool(config.app_id)}")
        self.stdout.write(f"app_secret_configured: {bool(config.app_secret)}")
        self.stdout.write(f"page_id_configured: {bool(config.page_id)}")
        self.stdout.write(f"page_token_configured: {bool(config.page_access_token)}")
        if config.page_id:
            self.stdout.write(f"page_id: {config.page_id}")

        if not config.is_publish_configured:
            self.stdout.write("publish_ready: no")
            return

        service = FacebookPageService(config)
        try:
            page = service.get_page()
        except FacebookNotConfigured as exc:
            raise CommandError(str(exc)) from exc
        except FacebookPublishError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("publish_ready: yes")
        self.stdout.write(f"page_name: {page.name}")
