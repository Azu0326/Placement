"""Instagram comment CRUD. Fake transport only — nothing reaches Meta."""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from poster.exceptions import InstagramNotConfigured
from poster.services.instagram_comments import InstagramCommentService

from .fakes import FakeTransport
from .test_facebook_service import FACEBOOK_SETTINGS


def service(responses=None, **overrides) -> tuple[InstagramCommentService, FakeTransport]:
    from poster.conf import FacebookPageConfig, get_facebook_config

    transport = FakeTransport(responses)
    config = get_facebook_config()
    config = FacebookPageConfig(
        page_id=overrides.get("page_id", config.page_id),
        page_access_token=overrides.get("page_access_token", config.page_access_token),
        app_id=config.app_id,
        app_secret=config.app_secret,
        graph_api_version=config.graph_api_version,
        timeout_seconds=config.timeout_seconds,
        instagram_account_id=overrides.get("instagram_account_id", "ig-1"),
    )
    return InstagramCommentService(config, transport), transport


@override_settings(**FACEBOOK_SETTINGS, INSTAGRAM_ACCOUNT_ID="ig-1")
class InstagramCommentServiceTests(SimpleTestCase):
    def test_list_media_and_comments(self):
        svc, transport = service(
            {
                "GET /ig-1/media": (
                    200,
                    {"data": [{"id": "media-1", "caption": "Hello", "media_type": "IMAGE"}]},
                ),
                "GET /media-1/comments": (
                    200,
                    {"data": [{"id": "c-1", "text": "Nice", "username": "pat"}]},
                ),
            }
        )
        media = svc.list_media()
        comments = svc.list_comments("media-1")
        self.assertEqual(media[0].media_id, "media-1")
        self.assertEqual(comments[0].comment_id, "c-1")
        self.assertEqual(comments[0].text, "Nice")
        self.assertEqual(transport.calls[0][0], "GET")

    def test_create_reply_and_delete(self):
        svc, transport = service(
            {
                "POST /media-1/comments": (200, {"id": "c-new"}),
                "POST /c-1/replies": (200, {"id": "c-reply"}),
                "DELETE /c-new": (200, {"success": True}),
            }
        )
        created = svc.create_comment("media-1", "Test comment")
        replied = svc.reply_to_comment("c-1", "Thanks")
        svc.delete_comment("c-new")
        self.assertEqual(created.comment_id, "c-new")
        self.assertEqual(replied.comment_id, "c-reply")
        self.assertEqual(transport.calls[0][2]["message"], "Test comment")
        self.assertEqual(transport.calls[1][2]["message"], "Thanks")
        self.assertEqual(transport.calls[2][0], "DELETE")

    def test_missing_token_is_not_a_network_call(self):
        svc, transport = service(page_access_token="", instagram_account_id="ig-1")
        with self.assertRaises(InstagramNotConfigured):
            svc.create_comment("media-1", "hello")
        self.assertEqual(transport.calls, [])

    def test_discovers_account_from_the_page_when_unset(self):
        svc, transport = service(
            {"GET /page-1": (200, {"instagram_business_account": {"id": "ig-from-page"}})},
            instagram_account_id="",
        )
        self.assertEqual(svc.account_id(), "ig-from-page")


@override_settings(**FACEBOOK_SETTINGS, INSTAGRAM_ACCOUNT_ID="ig-1")
class InstagramCommentCommandTests(SimpleTestCase):
    def test_create_prints_id_not_the_token(self):
        out = StringIO()
        fake = mock.Mock()
        fake.create_comment.return_value.comment_id = "c-9"
        with mock.patch(
            "poster.management.commands.instagram_comment.InstagramCommentService",
            return_value=fake,
        ):
            call_command("instagram_comment", "create", "--media-id", "m1", "--message", "Hi", stdout=out)
        self.assertIn("c-9", out.getvalue())
        self.assertNotIn("page-token-test-only", out.getvalue())

    def test_not_configured_is_a_command_error(self):
        with mock.patch(
            "poster.management.commands.instagram_comment.InstagramCommentService"
        ) as cls:
            cls.return_value.list_media.side_effect = InstagramNotConfigured()
            with self.assertRaises(CommandError):
                call_command("instagram_comment", "media")
