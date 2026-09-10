import json

from django.test import TestCase
from django.urls import reverse

from authentication.services.auth_service import BACKEND_PATH
from scraper.constants import JOB_STATUS_DRAFT
from scraper.models import ScrapeJob
from scraper.tests.helpers import make_job, make_user


class WizardUiTests(TestCase):
    def setUp(self):
        self.user = make_user("wizard.user")
        self.client.force_login(self.user, backend=BACKEND_PATH)

    def test_draft_creation(self):
        response = self.client.get(reverse("job_new"))
        self.assertEqual(response.status_code, 302)
        job = ScrapeJob.objects.get(owner=self.user)
        self.assertEqual(job.status, JOB_STATUS_DRAFT)
        self.assertEqual(self.client.get(reverse("job_wizard", args=[job.id])).status_code, 200)

    def test_variable_and_field_persist(self):
        job = make_job(self.user)
        payload = {
            "name": "Scholarships",
            "variables": [
                {
                    "name": "page",
                    "label": "Page",
                    "source_type": "counter",
                    "data_type": "integer",
                    "configuration": {"start_value": 1, "increment": 1},
                    "required": True,
                }
            ],
            "fields": [
                {
                    "name": "scholarship_name",
                    "label": "Scholarship Name",
                    "scope": "result_item",
                    "selector": "h3",
                    "extraction_method": "text_content",
                    "data_type": "text",
                }
            ],
        }
        response = self.client.post(
            reverse("api_wizard_step", args=[job.id, "basic"]),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.variables.get().name, "page")
        self.assertEqual(job.fields.get().name, "scholarship_name")

    def test_activation_validation(self):
        job = make_job(self.user)
        response = self.client.get(reverse("api_validate_job", args=[job.id]))
        body = response.json()
        self.assertFalse(body["ready"])
        self.assertTrue(body["errors"])
