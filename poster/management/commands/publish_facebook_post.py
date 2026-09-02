"""Publish a Scrapos content item (or a free-text message) to a Facebook Page.

Tokens are read from the environment. They are never printed, even on failure.

    python manage.py publish_facebook_post --message "Hello from Scrapos"
    python manage.py publish_facebook_post --content-id CT-902
    python manage.py publish_facebook_post --content-id CT-902 --dry-run
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive, make_aware

from poster.exceptions import FacebookNotConfigured, FacebookPublishError
from poster.services.facebook_service import FacebookPageService, format_content_message


def _lookup_content(content_id: str) -> dict:
    from frontend_demo.data import CONTENT_ITEMS, get_content

    needle = (content_id or "").strip()
    item = get_content(needle)
    if item.get("id") != needle:
        known = ", ".join(row["id"] for row in CONTENT_ITEMS)
        raise CommandError(f"Unknown content id {needle!r}. Known demo ids: {known}.")
    return item


def _parse_schedule(value: str) -> int:
    parsed = parse_datetime(value)
    if parsed is None:
        raise CommandError(
            "Could not parse --schedule-at. Use an ISO timestamp such as 2026-09-03T10:00:00+10:00."
        )
    if is_naive(parsed):
        parsed = make_aware(parsed)
    return int(parsed.timestamp())


class Command(BaseCommand):
    help = "Publish Scrapos content to the configured Facebook Page."

    def add_arguments(self, parser):
        parser.add_argument("--message", help="Post body. Overrides --content-id when both are set.")
        parser.add_argument(
            "--content-id",
            help="Demo content id (for example CT-902). Used until content lives in the database.",
        )
        parser.add_argument("--link", default="", help="Optional URL attached to the post.")
        parser.add_argument(
            "--image-url",
            default="",
            help="Public image URL. Publishes a photo post instead of a feed post.",
        )
        parser.add_argument(
            "--schedule-at",
            help="ISO timestamp between 10 minutes and 30 days from now (Facebook limit).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the post body without calling Facebook.",
        )

    def handle(self, *args, **options):
        message = (options.get("message") or "").strip()
        content_id = (options.get("content_id") or "").strip()
        if not message and content_id:
            message = format_content_message(_lookup_content(content_id))
        if not message and not options.get("link") and not options.get("image_url"):
            raise CommandError("Pass --message, --content-id, --link or --image-url.")

        scheduled_unix = None
        if options.get("schedule_at"):
            scheduled_unix = _parse_schedule(options["schedule_at"])

        if options["dry_run"]:
            self.stdout.write("Dry run — Facebook was not called.")
            self.stdout.write(f"message: {message}")
            if options.get("link"):
                self.stdout.write(f"link: {options['link']}")
            if options.get("image_url"):
                self.stdout.write(f"image_url: {options['image_url']}")
            if scheduled_unix is not None:
                when = datetime.fromtimestamp(scheduled_unix).isoformat()
                self.stdout.write(f"scheduled_unix: {scheduled_unix} ({when})")
            return

        service = FacebookPageService()
        try:
            published = service.publish(
                message=message,
                link=options.get("link") or "",
                image_url=options.get("image_url") or "",
                scheduled_unix=scheduled_unix,
            )
        except FacebookNotConfigured as exc:
            raise CommandError(str(exc)) from exc
        except FacebookPublishError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Published Facebook post {published.post_id}"))
