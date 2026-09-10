"""Posting a scraped record to Facebook is editor-only and owner-scoped."""

from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from authentication.roles import ROLE_EDITOR, ROLE_VIEWER
from authentication.services.auth_service import BACKEND_PATH
from poster.exceptions import FacebookNotConfigured
from poster.services.facebook_service import PublishedPost
from scraper.constants import RECORD_VALID
from scraper.models import ScrapedRecord
from scraper.tests.helpers import make_job, make_user, queued_run


class PublishScrapedFacebookTests(TestCase):
    def setUp(self):
        self.owner = make_user("fb.owner", ROLE_EDITOR)
        self.other = make_user("fb.other", ROLE_EDITOR)
        self.viewer = make_user("fb.viewer", ROLE_VIEWER)
        self.job = make_job(self.owner, name="Owned scholarships")
        self.run = queued_run(self.job, self.owner)
        self.record = ScrapedRecord.objects.create(
            run=self.run,
            job=self.job,
            sequence_number=1,
            detail_url="https://example.org/item",
            normalized_data={"title": "A scraped item"},
            status=RECORD_VALID,
        )
        self.url = reverse(
            "api_publish_facebook_record",
            args=[self.job.id, self.run.id, self.record.id],
        )

    def test_anonymous_is_redirected(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_viewer_is_forbidden(self):
        self.client.force_login(self.viewer, backend=BACKEND_PATH)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_other_editor_cannot_see_the_record(self):
        self.client.force_login(self.other, backend=BACKEND_PATH)
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_owner_form_post_publishes_and_redirects(self):
        self.client.force_login(self.owner, backend=BACKEND_PATH)
        with mock.patch("scraper.views.FacebookPageService") as cls:
            cls.return_value.publish.return_value = PublishedPost(
                post_id="page-1_ui", page_id="page-1"
            )
            response = self.client.post(self.url)
            cls.return_value.publish.assert_called_once()
            kwargs = cls.return_value.publish.call_args.kwargs
        self.assertEqual(kwargs["link"], "https://example.org/item")
        self.assertEqual(kwargs["message"], "A scraped item")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("run_records", args=[self.job.id, self.run.id]))

    def test_unconfigured_facebook_shows_a_generic_error(self):
        self.client.force_login(self.owner, backend=BACKEND_PATH)
        with mock.patch("scraper.views.FacebookPageService") as cls:
            cls.return_value.publish.side_effect = FacebookNotConfigured()
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)

    def test_results_page_shows_the_post_button_for_editors(self):
        self.client.force_login(self.owner, backend=BACKEND_PATH)
        response = self.client.get(reverse("run_records", args=[self.job.id, self.run.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Post")
        self.assertContains(response, self.url)

    @override_settings(FACEBOOK_PAGE_ID="page-1", FACEBOOK_PAGE_ACCESS_TOKEN="page-token-test-only")
    def test_json_post_returns_the_facebook_post_id(self):
        self.client.force_login(self.owner, backend=BACKEND_PATH)
        with mock.patch("scraper.views.FacebookPageService") as cls:
            cls.return_value.publish.return_value = PublishedPost(
                post_id="page-1_json", page_id="page-1"
            )
            response = self.client.post(
                self.url,
                data='{"include_image": false}',
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["post_id"], "page-1_json")
        self.assertNotIn("page-token-test-only", response.content.decode())
