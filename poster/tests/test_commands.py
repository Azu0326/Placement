"""Management commands: they must never print a Page access token on the happy path
except ``exchange_facebook_token``, which exists specifically to show one once.
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from poster.exceptions import FacebookAuthFailed, FacebookNotConfigured
from poster.services.facebook_service import ManagedPage, PageInfo, PublishedPost

from .test_facebook_service import FACEBOOK_SETTINGS


@override_settings(**FACEBOOK_SETTINGS)
class PublishCommandTests(SimpleTestCase):
    def test_dry_run_does_not_call_facebook(self):
        out = StringIO()
        with mock.patch("poster.management.commands.publish_facebook_post.FacebookPageService") as cls:
            call_command(
                "publish_facebook_post",
                "--content-id",
                "CT-902",
                "--dry-run",
                stdout=out,
            )
            cls.assert_not_called()
        self.assertIn("Campus living costs", out.getvalue())
        self.assertIn("Dry run", out.getvalue())

    def test_unknown_content_id_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("publish_facebook_post", "--content-id", "CT-missing")

    def test_publish_prints_post_id_not_the_token(self):
        out = StringIO()
        with mock.patch(
            "poster.management.commands.publish_facebook_post.FacebookPageService"
        ) as cls:
            cls.return_value.publish.return_value = PublishedPost(
                post_id="page-1_77", page_id="page-1"
            )
            call_command("publish_facebook_post", "--message", "Hello", stdout=out)
            cls.return_value.publish.assert_called_once()
        text = out.getvalue()
        self.assertIn("page-1_77", text)
        self.assertNotIn("page-token-test-only", text)

    def test_expired_token_surfaces_the_generic_message(self):
        with mock.patch(
            "poster.management.commands.publish_facebook_post.FacebookPageService"
        ) as cls:
            cls.return_value.publish.side_effect = FacebookAuthFailed()
            with self.assertRaises(CommandError) as ctx:
                call_command("publish_facebook_post", "--message", "Hello")
        self.assertIn("Reconnect the Page", str(ctx.exception))


@override_settings(**FACEBOOK_SETTINGS)
class StatusCommandTests(SimpleTestCase):
    def test_status_never_prints_the_token(self):
        out = StringIO()
        with mock.patch(
            "poster.management.commands.facebook_page_status.FacebookPageService"
        ) as cls:
            cls.return_value.get_page.return_value = PageInfo(page_id="page-1", name="DNC")
            call_command("facebook_page_status", stdout=out)
        text = out.getvalue()
        self.assertIn("publish_ready: yes", text)
        self.assertIn("page_name: DNC", text)
        self.assertNotIn("page-token-test-only", text)
        self.assertNotIn("app-secret-test-only", text)

    def test_missing_config_is_reported_without_calling_facebook(self):
        with override_settings(FACEBOOK_PAGE_ID="", FACEBOOK_PAGE_ACCESS_TOKEN=""):
            out = StringIO()
            call_command("facebook_page_status", stdout=out)
            self.assertIn("publish_ready: no", out.getvalue())


@override_settings(**FACEBOOK_SETTINGS)
class ExchangeCommandTests(SimpleTestCase):
    def test_prints_page_token_once_for_copying(self):
        out = StringIO()
        with mock.patch(
            "poster.management.commands.exchange_facebook_token.FacebookPageService"
        ) as cls:
            cls.return_value.exchange_long_lived_user_token.return_value = "long-lived"
            cls.return_value.list_managed_pages.return_value = [
                ManagedPage(
                    page_id="111",
                    name="DNC",
                    access_token="page-token-copy-once",
                    tasks=("CREATE_CONTENT",),
                )
            ]
            call_command("exchange_facebook_token", "--user-token", "short", stdout=out)
        text = out.getvalue()
        self.assertIn("FACEBOOK_PAGE_ID=111", text)
        self.assertIn("page-token-copy-once", text)
        self.assertIn("Do not commit", text)

    def test_not_configured_is_a_command_error(self):
        with mock.patch(
            "poster.management.commands.exchange_facebook_token.FacebookPageService"
        ) as cls:
            cls.return_value.exchange_long_lived_user_token.side_effect = FacebookNotConfigured(
                "Facebook app credentials are not configured. Ask an administrator."
            )
            with self.assertRaises(CommandError):
                call_command("exchange_facebook_token", "--user-token", "short")
