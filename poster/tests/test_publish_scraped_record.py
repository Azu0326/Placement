"""Publish a stored ScrapedRecord through the management command."""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from poster.services.facebook_service import PublishedPost
from scraper.constants import RECORD_VALID
from scraper.models import ScrapedRecord
from scraper.tests.helpers import make_job, make_user, queued_run

from .test_facebook_service import FACEBOOK_SETTINGS


@override_settings(**FACEBOOK_SETTINGS)
class PublishScrapedRecordCommandTests(TestCase):
    def setUp(self):
        self.user = make_user("poster.owner")
        self.job = make_job(self.user, name="Scholarships")
        self.run = queued_run(self.job, self.user)
        self.record = ScrapedRecord.objects.create(
            run=self.run,
            job=self.job,
            sequence_number=1,
            detail_url="https://search.studyaustralia.gov.au/scholarships/abc",
            source_url="https://search.studyaustralia.gov.au/scholarships?page=1",
            normalized_data={
                "scholarship_name": "Destination Australia",
                "description": "Study in regional Australia.",
                "image": "https://example.org/hero.jpg",
            },
            status=RECORD_VALID,
        )

    def test_dry_run_maps_the_scraped_row(self):
        out = StringIO()
        with mock.patch("poster.management.commands.publish_facebook_post.FacebookPageService") as cls:
            call_command(
                "publish_facebook_post",
                "--record-id",
                str(self.record.id),
                "--dry-run",
                stdout=out,
            )
            cls.assert_not_called()
        text = out.getvalue()
        self.assertIn("Destination Australia", text)
        self.assertIn("https://search.studyaustralia.gov.au/scholarships/abc", text)
        self.assertNotIn("https://example.org/hero.jpg", text)

    def test_with_image_dry_run_includes_the_photo_url(self):
        out = StringIO()
        call_command(
            "publish_facebook_post",
            "--record-id",
            str(self.record.id),
            "--with-image",
            "--dry-run",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("image_url: https://example.org/hero.jpg", text)
        self.assertIn("Destination Australia", text)

    def test_publish_sends_mapped_fields(self):
        out = StringIO()
        with mock.patch(
            "poster.management.commands.publish_facebook_post.FacebookPageService"
        ) as cls:
            cls.return_value.publish.return_value = PublishedPost(
                post_id="page-1_rec", page_id="page-1"
            )
            call_command("publish_facebook_post", "--record-id", str(self.record.id), stdout=out)
            kwargs = cls.return_value.publish.call_args.kwargs
        self.assertEqual(kwargs["link"], "https://search.studyaustralia.gov.au/scholarships/abc")
        self.assertIn("Destination Australia", kwargs["message"])
        self.assertEqual(kwargs["image_url"], "")
        self.assertIn("page-1_rec", out.getvalue())
        self.assertNotIn("page-token-test-only", out.getvalue())
