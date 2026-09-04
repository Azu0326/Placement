"""Exchange a short-lived user token for Page tokens.

A Graph API Explorer user token lasts one to two hours. This command upgrades
it and lists the Pages the user can publish to. The Page access token is shown
once on stdout so it can be copied into FACEBOOK_PAGE_ACCESS_TOKEN.

    python manage.py exchange_facebook_token --user-token EAAB...

Never commit the printed values. They are not written to a file.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from poster.exceptions import FacebookNotConfigured, FacebookPublishError
from poster.services.facebook_service import FacebookPageService


class Command(BaseCommand):
    help = "Exchange a short-lived Facebook user token for long-lived Page tokens."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-token",
            required=True,
            help="Short-lived user token from Graph API Explorer. Shown only in this shell.",
        )

    def handle(self, *args, **options):
        service = FacebookPageService()
        try:
            long_lived = service.exchange_long_lived_user_token(options["user_token"])
            pages = service.list_managed_pages(long_lived)
        except FacebookNotConfigured as exc:
            raise CommandError(str(exc)) from exc
        except FacebookPublishError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.WARNING(
                "Long-lived user token (expires in about 60 days). Store privately, never in git:"
            )
        )
        self.stdout.write(long_lived)
        self.stdout.write("")

        if not pages:
            self.stdout.write("No Pages were returned. Confirm the user is a Page admin.")
            return

        self.stdout.write(self.style.SUCCESS(f"Managed Pages ({len(pages)}):"))
        for page in pages:
            self.stdout.write("")
            self.stdout.write(f"  name: {page.name}")
            self.stdout.write(f"  FACEBOOK_PAGE_ID={page.page_id}")
            if page.tasks:
                self.stdout.write(f"  tasks: {', '.join(page.tasks)}")
            self.stdout.write("  FACEBOOK_PAGE_ACCESS_TOKEN (often non-expiring for this Page):")
            self.stdout.write(f"  {page.access_token}")
        self.stdout.write("")
        self.stdout.write("Copy one Page id and token into .env. Do not commit them.")
