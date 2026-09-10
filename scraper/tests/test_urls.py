from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from scraper.views import ExportCreateAPI, PublishScrapedFacebookAPI, RunActionAPI


class ExportUrlRoutingTests(SimpleTestCase):
    def test_export_url_resolves_to_export_create_api(self):
        path = reverse("api_export_create", args=[uuid4(), uuid4()])
        match = resolve(path)
        self.assertEqual(match.url_name, "api_export_create")
        self.assertEqual(match.func.view_class, ExportCreateAPI)
        self.assertNotEqual(match.func.view_class, RunActionAPI)

    def test_facebook_publish_url_is_not_the_run_action_wildcard(self):
        path = reverse("api_publish_facebook_record", args=[uuid4(), uuid4(), uuid4()])
        match = resolve(path)
        self.assertEqual(match.func.view_class, PublishScrapedFacebookAPI)
        self.assertNotEqual(match.func.view_class, RunActionAPI)
