"""Scraped-record → Facebook post mapping. No Graph API calls."""

from __future__ import annotations

from django.test import SimpleTestCase

from django.test import override_settings

from poster.exceptions import FacebookPublishFailed
from poster.services.scraped import payload_from_scraped

from .test_facebook_service import FACEBOOK_SETTINGS, service


class ScrapedPayloadTests(SimpleTestCase):
    def test_scholarship_row_becomes_message_and_link(self):
        draft = payload_from_scraped(
            {
                "scholarship_name": "Destination Australia",
                "description": "Regional campuses.",
                "detail_url": "https://search.studyaustralia.gov.au/scholarships/abc",
            },
            detail_url="https://search.studyaustralia.gov.au/scholarships/abc",
        )
        self.assertIn("Destination Australia", draft.message)
        self.assertIn("Regional campuses.", draft.message)
        self.assertEqual(draft.link, "https://search.studyaustralia.gov.au/scholarships/abc")
        self.assertEqual(draft.image_url, "")
        self.assertFalse(draft.uses_photo)

    def test_image_is_ignored_unless_requested(self):
        draft = payload_from_scraped(
            {
                "title": "Campus living",
                "image": "https://example.org/hero.jpg",
                "detail_url": "https://example.org/guide",
            }
        )
        self.assertEqual(draft.link, "https://example.org/guide")
        self.assertEqual(draft.image_url, "")

    def test_with_image_uses_photo_and_keeps_the_link_in_the_caption(self):
        draft = payload_from_scraped(
            {
                "title": "Campus living",
                "image": "https://example.org/hero.jpg",
                "detail_url": "https://example.org/guide",
            },
            include_image=True,
        )
        self.assertTrue(draft.uses_photo)
        self.assertEqual(draft.image_url, "https://example.org/hero.jpg")
        self.assertEqual(draft.link, "")
        self.assertIn("https://example.org/guide", draft.message)

    def test_empty_row_is_rejected(self):
        with self.assertRaises(FacebookPublishFailed):
            payload_from_scraped({})


@override_settings(**FACEBOOK_SETTINGS)
class ScrapedPublishTransportTests(SimpleTestCase):
    def test_link_post_hits_the_feed_edge(self):
        draft = payload_from_scraped(
            {"title": "Scholarships", "detail_url": "https://example.org/s"}
        )
        svc, transport = service({"POST /page-1/feed": (200, {"id": "page-1_link"})})
        published = svc.publish(message=draft.message, link=draft.link, image_url=draft.image_url)
        self.assertEqual(published.post_id, "page-1_link")
        method, path, body = transport.calls[0]
        self.assertEqual((method, path), ("POST", "/page-1/feed"))
        self.assertEqual(body["link"], "https://example.org/s")
        self.assertEqual(body["message"], "Scholarships")

    def test_photo_post_hits_the_photos_edge(self):
        draft = payload_from_scraped(
            {"title": "Campus", "image": "https://example.org/hero.jpg"},
            include_image=True,
        )
        svc, transport = service({"POST /page-1/photos": (200, {"id": "photo-9", "post_id": "page-1_photo"})})
        published = svc.publish(message=draft.message, link=draft.link, image_url=draft.image_url)
        method, path, body = transport.calls[0]
        self.assertEqual((method, path), ("POST", "/page-1/photos"))
        self.assertEqual(body["url"], "https://example.org/hero.jpg")
        self.assertEqual(body["caption"], "Campus")
        self.assertEqual(published.post_id, "page-1_photo")
