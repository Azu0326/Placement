import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from authentication.services.auth_service import BACKEND_PATH
from scraper.constants import CSV_HEADERS, ORIGIN_CSV, ORIGIN_MANUAL, RUN_COMPLETED
from scraper.models import ScrapeField, VariableParameter
from scraper.services.config import functional_field, functional_variable, normalize_field, normalize_variable
from scraper.services.config_csv import apply_import, export_job_csv, preview_counter, preview_import, template_csv
from scraper.services.exporters import generate_csv, generate_sqlite
from scraper.services.http_fetcher import FetchResult
from scraper.services.jobs import replace_fields, replace_variables
from scraper.services.orchestrator import execute_run
from scraper.tests.helpers import configure_listing_job, html, make_job, make_user, queued_run
from scraper.tests.test_integration import fake_fetch

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "csv" / "study_australia.csv"


def csv_bytes(path=FIXTURE):
    return path.read_bytes()


class ManualEntryRegressionTests(TestCase):
    def setUp(self):
        self.user = make_user("manual.csv")
        self.client.force_login(self.user, backend=BACKEND_PATH)
        self.job = make_job(self.user, start_url="https://search.studyaustralia.gov.au/scholarships?page=1")

    def _save(self, step, payload):
        return self.client.post(
            reverse("api_wizard_step", args=[self.job.id, step]),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_create_counter_html_field_result_and_detail_manually(self):
        response = self._save(
            "variables",
            {
                "variables": [
                    {
                        "name": "page",
                        "label": "Page Number",
                        "source_type": "counter",
                        "scope": "variable",
                        "data_type": "integer",
                        "configuration": {"start_value": 1, "increment": 1},
                        "required": True,
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.job.variables.get().name, "page")
        self.assertEqual(self.job.variables.get().created_via, ORIGIN_MANUAL)

        response = self._save(
            "results",
            {
                "result_selector": ".scholarship-list-card",
                "detail_link_selector": "h3 a",
                "follow_detail_pages": True,
                "unique_field_name": "detail_url",
                "fields": [
                    {
                        "name": "scholarship_name",
                        "label": "Scholarship Name",
                        "scope": "result_item",
                        "selector": "h3 a",
                        "extraction_method": "text_content",
                    },
                    {
                        "name": "detail_url",
                        "label": "Detail URL",
                        "scope": "result_item",
                        "selector": "h3 a",
                        "extraction_method": "attribute",
                        "attribute_name": "href",
                        "data_type": "url",
                        "unique": True,
                    },
                    {
                        "name": "description",
                        "label": "Description",
                        "scope": "detail_page",
                        "selector": "p",
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.result_selector, ".scholarship-list-card")
        self.assertEqual(self.job.fields.count(), 3)

    def test_edit_and_delete_manual_rows(self):
        replace_variables(self.job, [{"name": "page", "source_type": "counter", "configuration": {"start_value": 1, "increment": 1}}])
        replace_fields(self.job, [{"name": "title", "label": "Title", "scope": "result_item", "selector": "h3"}])
        self._save("variables", {"variables": [{"name": "page", "label": "Page", "source_type": "counter", "configuration": {"start_value": 2, "increment": 1}}]})
        self.assertEqual(self.job.variables.get().configuration["start_value"], 2)
        self._save("variables", {"variables": []})
        self.assertEqual(self.job.variables.count(), 0)
        self._save("results", {"fields": []})
        self.assertEqual(self.job.fields.count(), 0)

    def test_existing_job_still_loads(self):
        configure_listing_job(self.job)
        self.assertEqual(self.client.get(reverse("job_wizard", args=[self.job.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("job_detail", args=[self.job.id])).status_code, 200)


class CsvImportTests(TestCase):
    def setUp(self):
        self.user = make_user("csv.owner")
        self.client.force_login(self.user, backend=BACKEND_PATH)
        self.job = make_job(
            self.user,
            start_url="https://search.studyaustralia.gov.au/scholarships?page=1",
            url_template="https://search.studyaustralia.gov.au/scholarships?page={{page}}",
        )

    def test_download_template(self):
        response = self.client.get(reverse("api_config_csv_template"))
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        self.assertTrue(text.startswith(",".join(CSV_HEADERS)))
        self.assertIn("REPLACE_WITH_VERIFIED", text)

    def test_preview_does_not_save(self):
        response = self.client.post(
            reverse("api_config_csv_preview", args=[self.job.id]),
            data={"mode": "merge", "csv": csv_bytes().decode("utf-8")},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(body["summary"]["new_rows"], 1)
        self.assertEqual(self.job.variables.count(), 0)
        self.assertEqual(self.job.fields.count(), 0)

    def test_import_valid_csv_and_edit_manually(self):
        response = self.client.post(
            reverse("api_config_csv_import", args=[self.job.id]),
            data={"mode": "merge", "csv": csv_bytes().decode("utf-8")},
        )
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.variables.get().name, "page")
        self.assertEqual(self.job.variables.get().created_via, ORIGIN_CSV)
        self.assertEqual(self.job.result_selector, ".scholarship-list-card")
        self.assertTrue(self.job.fields.filter(name="scholarship_name", created_via=ORIGIN_CSV).exists())

        self.client.post(
            reverse("api_wizard_step", args=[self.job.id, "variables"]),
            data=json.dumps(
                {
                    "variables": [
                        {
                            "name": "page",
                            "label": "Page Number",
                            "source_type": "counter",
                            "configuration": {"start_value": 1, "increment": 1, "maximum_value": 50},
                            "created_via": ORIGIN_CSV,
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        page = self.job.variables.get()
        self.assertEqual(page.created_via, ORIGIN_CSV)
        self.assertEqual(page.last_updated_via, ORIGIN_MANUAL)
        self.assertEqual(page.configuration.get("maximum_value"), 50)

        self.client.post(
            reverse("api_wizard_step", args=[self.job.id, "results"]),
            data=json.dumps(
                {
                    "result_selector": self.job.result_selector,
                    "fields": [
                        {"name": "provider_name", "label": "Provider", "scope": "result_item", "selector": "a"},
                        *[{"name": item.name, "label": item.label, "scope": item.scope, "selector": item.selector, "extraction_method": item.extraction_method, "attribute_name": item.attribute_name, "data_type": item.data_type, "created_via": item.created_via} for item in self.job.fields.all()],
                    ],
                }
            ),
            content_type="application/json",
        )
        self.assertTrue(self.job.fields.filter(name="provider_name", created_via=ORIGIN_MANUAL).exists())

        self.client.post(
            reverse("api_wizard_step", args=[self.job.id, "results"]),
            data=json.dumps(
                {
                    "result_selector": self.job.result_selector,
                    "fields": [
                        {"name": item.name, "label": item.label, "scope": item.scope, "selector": item.selector, "extraction_method": item.extraction_method, "attribute_name": item.attribute_name, "created_via": item.created_via}
                        for item in self.job.fields.exclude(name="description")
                    ],
                }
            ),
            content_type="application/json",
        )
        self.assertFalse(self.job.fields.filter(name="description").exists())

    def test_merge_keeps_omitted_manual_rows(self):
        replace_variables(self.job, [{"name": "region", "source_type": "fixed", "configuration": {"fixed_value": "AU"}}])
        apply_import(self.job, csv_bytes(), mode="merge", user=self.user)
        names = set(self.job.variables.values_list("name", flat=True))
        self.assertEqual(names, {"page", "region"})
        self.assertEqual(self.job.variables.get(name="region").created_via, ORIGIN_MANUAL)

    def test_replace_requires_confirmation_and_then_replaces(self):
        replace_variables(self.job, [{"name": "region", "source_type": "fixed"}])
        with self.assertRaises(Exception):
            apply_import(self.job, csv_bytes(), mode="replace", confirm_replace=False, user=self.user)
        self.assertTrue(self.job.variables.filter(name="region").exists())
        apply_import(self.job, csv_bytes(), mode="replace", confirm_replace=True, user=self.user)
        self.assertFalse(self.job.variables.filter(name="region").exists())
        self.assertTrue(self.job.variables.filter(name="page").exists())

    def test_invalid_csv_does_not_change_manual_rows(self):
        replace_variables(self.job, [{"name": "page", "source_type": "counter", "configuration": {"start_value": 1, "increment": 1}}])
        bad = template_csv().replace(b"page", b"1bad")
        preview = preview_import(self.job, template_csv(), mode="merge")
        self.assertTrue(preview["rows"])
        try:
            apply_import(self.job, bad, mode="merge", user=self.user)
        except Exception:
            pass
        self.assertEqual(self.job.variables.get().name, "page")

    def test_export_mixed_and_reimport(self):
        apply_import(self.job, csv_bytes(), mode="merge", user=self.user)
        replace_variables(
            self.job,
            [
                {"name": "page", "source_type": "counter", "configuration": {"start_value": 1, "increment": 1}, "created_via": ORIGIN_CSV},
                {"name": "region", "source_type": "fixed", "configuration": {"fixed_value": "AU"}},
            ],
        )
        exported = export_job_csv(self.job)
        self.assertIn(b"region", exported)
        self.assertIn(b"page", exported)
        other = make_job(self.user, name="Reimport target")
        apply_import(other, exported, mode="replace", confirm_replace=True, user=self.user)
        self.assertEqual(set(other.variables.values_list("name", flat=True)), {"page", "region"})

    def test_counter_previews_urls_not_selector_matches(self):
        result = preview_counter(
            self.job,
            {"name": "page", "source_type": "counter", "configuration": {"start_value": 1, "increment": 1}},
        )
        self.assertEqual(result["values"], [1, 2, 3])
        self.assertEqual(
            result["rendered_urls"],
            [
                "https://search.studyaustralia.gov.au/scholarships?page=1",
                "https://search.studyaustralia.gov.au/scholarships?page=2",
                "https://search.studyaustralia.gov.au/scholarships?page=3",
            ],
        )
        self.assertNotIn("0 matches", json.dumps(result))


class CsvParityTests(TestCase):
    def setUp(self):
        self.user = make_user("parity.user")

    def test_manual_and_csv_counter_are_equivalent(self):
        manual = make_job(self.user, name="Manual parity")
        replace_variables(
            manual,
            [
                {
                    "name": "page",
                    "label": "Page Number",
                    "source_type": "counter",
                    "scope": "variable",
                    "data_type": "integer",
                    "required": True,
                    "configuration": {"start_value": 1, "increment": 1, "parameter": "page"},
                }
            ],
        )
        imported = make_job(self.user, name="CSV parity")
        apply_import(imported, csv_bytes(), mode="merge", user=self.user)
        left = functional_variable(normalize_variable({
            "name": manual.variables.get().name,
            "label": manual.variables.get().label,
            "source_type": manual.variables.get().source_type,
            "scope": manual.variables.get().scope,
            "data_type": manual.variables.get().data_type,
            "required": manual.variables.get().required,
            "configuration": manual.variables.get().configuration,
        }))
        right = functional_variable(normalize_variable({
            "name": imported.variables.get().name,
            "label": imported.variables.get().label,
            "source_type": imported.variables.get().source_type,
            "scope": imported.variables.get().scope,
            "data_type": imported.variables.get().data_type,
            "required": imported.variables.get().required,
            "configuration": imported.variables.get().configuration,
        }))
        self.assertEqual(left["name"], right["name"])
        self.assertEqual(left["source_type"], right["source_type"])
        self.assertEqual(left["configuration"]["start_value"], right["configuration"]["start_value"])
        self.assertEqual(left["configuration"]["increment"], right["configuration"]["increment"])

        left_field = functional_field(normalize_field({
            "name": "scholarship_name",
            "label": "Scholarship Name",
            "scope": "result_item",
            "selector": "h3 a",
            "extraction_method": "text_content",
            "data_type": "text",
            "required": True,
            "transformations": ["trim", "normalize_whitespace"],
        }))
        imported_field = imported.fields.get(name="scholarship_name")
        right_field = functional_field(normalize_field({
            "name": imported_field.name,
            "label": imported_field.label,
            "scope": imported_field.scope,
            "selector": imported_field.selector,
            "extraction_method": imported_field.extraction_method,
            "data_type": imported_field.data_type,
            "required": imported_field.required,
            "transformations": imported_field.transformations,
        }))
        self.assertEqual(left_field["selector"], right_field["selector"])
        self.assertEqual(left_field["extraction_method"], right_field["extraction_method"])

    @override_settings(SCRAPER_INLINE_WORKER=False, SCRAPER_DEFAULT_DELAY_SECONDS=0)
    @patch("scraper.services.orchestrator.fetch_page", side_effect=fake_fetch)
    def test_csv_job_executes_and_exports(self, _mock):
        job = make_job(
            self.user,
            name="CSV run",
            start_url="https://search.studyaustralia.gov.au/scholarships?page=1",
            url_template="https://search.studyaustralia.gov.au/scholarships?page={{page}}",
        )
        apply_import(job, csv_bytes(), mode="merge", user=self.user)
        job.maximum_pages = 3
        job.save(update_fields=["maximum_pages"])
        run = queued_run(job, self.user)
        execute_run(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, RUN_COMPLETED)
        self.assertGreaterEqual(run.records_created, 1)
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "out.csv"
            sqlite_path = Path(tmp) / "out.sqlite3"
            csv_count = generate_csv(run, csv_path)
            sqlite_count = generate_sqlite(run, sqlite_path)
            self.assertEqual(csv_count, sqlite_count)
            import sqlite3

            conn = sqlite3.connect(sqlite_path)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.close()


class CsvPermissionTests(TestCase):
    def setUp(self):
        self.owner = make_user("csv.perm.owner")
        self.other = make_user("csv.perm.other")
        self.job = make_job(self.owner)

    def test_other_user_cannot_import_or_export(self):
        self.client.force_login(self.other, backend=BACKEND_PATH)
        self.assertEqual(self.client.get(reverse("api_config_csv_export", args=[self.job.id])).status_code, 404)
        response = self.client.post(
            reverse("api_config_csv_import", args=[self.job.id]),
            data={"mode": "merge", "csv": csv_bytes().decode("utf-8")},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(VariableParameter.objects.filter(job=self.job).count(), 0)
        self.assertEqual(ScrapeField.objects.filter(job=self.job).count(), 0)
