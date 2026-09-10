from django.test import SimpleTestCase

from scraper.services.validation import validate_job_payload


class ValidationTests(SimpleTestCase):
    def test_active_job_needs_fields_and_url(self):
        errors = validate_job_payload({"name": "X", "status": "active"}, activating=True)
        self.assertTrue(any("URL" in err or "starting" in err.lower() for err in errors))
        self.assertTrue(any("field" in err.lower() for err in errors))

    def test_template_requires_variable(self):
        errors = validate_job_payload(
            {
                "name": "X",
                "start_url": "https://example.com/?page=1",
                "url_template": "https://example.com/?page={{page}}",
                "fields": [{"name": "title", "label": "Title"}],
                "variables": [],
            },
            activating=True,
        )
        self.assertTrue(any("undefined" in err.lower() for err in errors))

    def test_unique_names(self):
        errors = validate_job_payload(
            {
                "name": "X",
                "start_url": "https://example.com/",
                "variables": [
                    {"name": "page", "source_type": "counter"},
                    {"name": "page", "source_type": "fixed"},
                ],
                "fields": [{"name": "title", "label": "T"}],
            }
        )
        self.assertTrue(any("unique" in err.lower() for err in errors))
