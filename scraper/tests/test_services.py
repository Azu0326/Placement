from django.test import SimpleTestCase, override_settings

from scraper.services.pagination import PaginationState, should_stop
from scraper.services.ssrf import RequestPolicyError, validate_url
from scraper.services.transforms import apply_pipeline
from scraper.services.types import normalize
from scraper.services.url_template import TemplateError, infer_page_template, render
from scraper.services.validation import field_name_from_label, validate_identifier
from scraper.services.variables import detect_cycles


class UrlTemplateTests(SimpleTestCase):
    def test_renders_page_variable(self):
        url = render("https://search.studyaustralia.gov.au/scholarships?page={{page}}", {"page": 2})
        self.assertEqual(url, "https://search.studyaustralia.gov.au/scholarships?page=2")

    def test_missing_variable(self):
        with self.assertRaises(TemplateError):
            render("https://example.com/{{page}}", {})

    def test_infers_page_template(self):
        self.assertEqual(
            infer_page_template("https://search.studyaustralia.gov.au/scholarships?page=1"),
            "https://search.studyaustralia.gov.au/scholarships?page={{page}}",
        )


class TransformTests(SimpleTestCase):
    def test_pipeline_order(self):
        value = apply_pipeline("  Hello   World  ", ["trim", "normalize_whitespace", "lowercase"])
        self.assertEqual(value, "hello world")

    def test_absolute_url(self):
        value = apply_pipeline("/path", ["resolve_absolute_url"], base_url="https://example.com/x")
        self.assertEqual(value, "https://example.com/path")

    def test_formula_safe_export_prefix(self):
        from scraper.services.exporters import _formula_safe

        self.assertEqual(_formula_safe("=CMD"), "'=CMD")
        self.assertEqual(_formula_safe("plain"), "plain")

    def test_parse_integer(self):
        self.assertEqual(apply_pipeline("AUD $750", ["parse_integer"]), 750)


class TypeTests(SimpleTestCase):
    def test_required_conversion(self):
        self.assertEqual(normalize("12", "integer"), 12)
        self.assertEqual(normalize(["a", "b"], "list"), ["a", "b"])


class IdentifierTests(SimpleTestCase):
    def test_label_to_name(self):
        self.assertEqual(field_name_from_label("Scholarship Name"), "scholarship_name")

    def test_reserved_rejected(self):
        self.assertIsNotNone(validate_identifier("password"))
        self.assertIsNone(validate_identifier("scholarship_name"))


class CycleTests(SimpleTestCase):
    def test_circular_variables(self):
        cycles = detect_cycles(
            [
                {"name": "a", "configuration": {"depends_on": "b"}},
                {"name": "b", "configuration": {"depends_on": "a"}},
            ]
        )
        self.assertTrue(cycles)


class PaginationStopTests(SimpleTestCase):
    def test_repeated_page(self):
        state = PaginationState(page=2, url="https://ex.test", fingerprints=["abc"])
        reason = should_stop(
            {"stop_conditions": ["repeated_page"]},
            state,
            result_count=2,
            new_unique=1,
            new_details=1,
            next_url="https://ex.test?page=3",
            next_disabled=False,
            fingerprint="abc",
            cancelled=False,
            runtime_exceeded=False,
            records_created=2,
            max_pages=100,
            max_records=100,
        )
        self.assertEqual(reason, "repeated_page")

    def test_counter_increments(self):
        from scraper.services.variables import resolve_variable

        value = resolve_variable(
            {"name": "page", "source_type": "counter", "data_type": "integer", "configuration": {"start_value": 1, "increment": 1}},
            page_number=2,
        )
        self.assertEqual(value, 2)


class SsrfTests(SimpleTestCase):
    def test_rejects_localhost(self):
        with self.assertRaises(RequestPolicyError):
            validate_url("http://127.0.0.1/")

    def test_rejects_file(self):
        with self.assertRaises(RequestPolicyError):
            validate_url("file:///etc/passwd")

    def test_rejects_credentials(self):
        with self.assertRaises(RequestPolicyError):
            validate_url("https://user:pass@example.com/")

    def test_rejects_without_resolve_for_metadata(self):
        with self.assertRaises(RequestPolicyError):
            validate_url("http://169.254.169.254/latest/meta-data", resolve=False)
