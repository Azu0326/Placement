"""FacebookPageService: Graph API error translation and publishing calls.

Every test drives a fake transport. Nothing here reaches Facebook.
"""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from poster.conf import get_facebook_config
from poster.exceptions import (
    FacebookAuthFailed,
    FacebookNotConfigured,
    FacebookPermissionDenied,
    FacebookPublishFailed,
    FacebookUnavailable,
)
from poster.services.facebook_service import FacebookPageService, format_content_message

from .fakes import FakeTransport

FACEBOOK_SETTINGS = {
    "FACEBOOK_PAGE_ID": "page-1",
    "FACEBOOK_PAGE_ACCESS_TOKEN": "page-token-test-only",
    "FACEBOOK_APP_ID": "app-1",
    "FACEBOOK_APP_SECRET": "app-secret-test-only",
    "FACEBOOK_GRAPH_API_VERSION": "v22.0",
    "FACEBOOK_GRAPH_TIMEOUT_SECONDS": 5,
}


def service(responses=None, **overrides) -> tuple[FacebookPageService, FakeTransport]:
    transport = FakeTransport(responses)
    config = get_facebook_config()
    if overrides:
        # dataclasses.replace would also work; constructing keeps tests explicit.
        from poster.conf import FacebookPageConfig

        config = FacebookPageConfig(
            page_id=overrides.get("page_id", config.page_id),
            page_access_token=overrides.get("page_access_token", config.page_access_token),
            app_id=overrides.get("app_id", config.app_id),
            app_secret=overrides.get("app_secret", config.app_secret),
            graph_api_version=overrides.get("graph_api_version", config.graph_api_version),
            timeout_seconds=overrides.get("timeout_seconds", config.timeout_seconds),
        )
    return FacebookPageService(config, transport), transport


@override_settings(**FACEBOOK_SETTINGS)
class PublishTests(SimpleTestCase):
    def test_feed_post_sends_message_and_page_token(self):
        svc, transport = service({"POST /page-1/feed": (200, {"id": "page-1_99"})})
        published = svc.publish(message="Hello from Scrapos")

        self.assertEqual(published.post_id, "page-1_99")
        self.assertEqual(published.page_id, "page-1")
        method, path, body = transport.calls[0]
        self.assertEqual((method, path), ("POST", "/page-1/feed"))
        self.assertEqual(body["message"], "Hello from Scrapos")
        self.assertEqual(body["access_token"], "page-token-test-only")

    def test_link_and_schedule_are_forwarded(self):
        svc, transport = service({"POST /page-1/feed": (200, {"id": "page-1_100"})})
        svc.publish(message="Intake", link="https://example.org/guide", scheduled_unix=1_800_000_000)

        body = transport.calls[0][2]
        self.assertEqual(body["link"], "https://example.org/guide")
        self.assertEqual(body["published"], "false")
        self.assertEqual(body["scheduled_publish_time"], "1800000000")

    def test_image_url_uses_photos_edge(self):
        svc, transport = service({"POST /page-1/photos": (200, {"id": "photo-1", "post_id": "page-1_101"})})
        published = svc.publish(message="Campus", image_url="https://example.org/hero.jpg")

        self.assertEqual(published.post_id, "page-1_101")
        method, path, body = transport.calls[0]
        self.assertEqual((method, path), ("POST", "/page-1/photos"))
        self.assertEqual(body["url"], "https://example.org/hero.jpg")
        self.assertEqual(body["caption"], "Campus")

    def test_empty_payload_is_rejected_without_a_network_call(self):
        svc, transport = service()
        with self.assertRaises(FacebookPublishFailed):
            svc.publish()
        self.assertEqual(transport.calls, [])

    def test_missing_page_credentials_are_not_a_network_error(self):
        svc, transport = service(page_id="", page_access_token="")
        with self.assertRaises(FacebookNotConfigured):
            svc.publish(message="hello")
        self.assertEqual(transport.calls, [])


@override_settings(**FACEBOOK_SETTINGS)
class ErrorTranslationTests(SimpleTestCase):
    def test_graph_codes_map_to_application_errors(self):
        cases = [
            (190, 401, FacebookAuthFailed),
            (102, 400, FacebookAuthFailed),
            (10, 403, FacebookPermissionDenied),
            (200, 403, FacebookPermissionDenied),
            (4, 500, FacebookUnavailable),
            (100, 400, FacebookPublishFailed),
        ]
        for code, status, expected in cases:
            with self.subTest(code=code):
                svc, _ = service(
                    {
                        "POST /page-1/feed": (
                            status,
                            {"error": {"code": code, "message": "should-never-surface"}},
                        )
                    }
                )
                with self.assertRaises(expected) as ctx:
                    svc.publish(message="hello")
                self.assertNotIn("should-never-surface", str(ctx.exception))
                self.assertNotIn("page-token", str(ctx.exception))

    def test_expired_token_message_is_generic(self):
        svc, _ = service(
            {"POST /page-1/feed": (401, {"error": {"code": 190, "message": "Invalid OAuth access token."}})}
        )
        with self.assertRaises(FacebookAuthFailed) as ctx:
            svc.publish(message="hello")
        self.assertEqual(
            str(ctx.exception),
            "Facebook access has expired. Reconnect the Page to resume publishing.",
        )


@override_settings(**FACEBOOK_SETTINGS)
class TokenExchangeTests(SimpleTestCase):
    def test_exchange_and_list_pages(self):
        svc, transport = service(
            {
                "GET /oauth/access_token": (200, {"access_token": "long-lived-user", "expires_in": 5184000}),
                "GET /me/accounts": (
                    200,
                    {
                        "data": [
                            {
                                "id": "111",
                                "name": "DNC",
                                "access_token": "page-token-never-log",
                                "tasks": ["CREATE_CONTENT", "MANAGE"],
                            }
                        ]
                    },
                ),
            }
        )
        long_lived = svc.exchange_long_lived_user_token("short-lived")
        pages = svc.list_managed_pages(long_lived)

        self.assertEqual(long_lived, "long-lived-user")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].page_id, "111")
        self.assertEqual(pages[0].name, "DNC")
        self.assertEqual(pages[0].access_token, "page-token-never-log")
        self.assertIn("CREATE_CONTENT", pages[0].tasks)
        self.assertEqual(transport.calls[0][2]["grant_type"], "fb_exchange_token")
        self.assertEqual(transport.calls[0][2]["fb_exchange_token"], "short-lived")

    def test_exchange_requires_app_credentials(self):
        svc, transport = service(app_id="", app_secret="")
        with self.assertRaises(FacebookNotConfigured):
            svc.exchange_long_lived_user_token("short-lived")
        self.assertEqual(transport.calls, [])


@override_settings(**FACEBOOK_SETTINGS)
class PageStatusTests(SimpleTestCase):
    def test_get_page_returns_name_only(self):
        svc, transport = service({"GET /page-1": (200, {"id": "page-1", "name": "DNC Australia"})})
        info = svc.get_page()
        self.assertEqual(info.name, "DNC Australia")
        self.assertEqual(info.page_id, "page-1")
        self.assertEqual(transport.calls[0][2]["fields"], "id,name")


class FormatContentTests(SimpleTestCase):
    def test_uses_the_content_title(self):
        self.assertEqual(
            format_content_message({"title": "Campus living costs — Melbourne vs Sydney"}),
            "Campus living costs — Melbourne vs Sydney",
        )

    def test_blank_title_is_rejected(self):
        with self.assertRaises(FacebookPublishFailed):
            format_content_message({"title": "  "})
