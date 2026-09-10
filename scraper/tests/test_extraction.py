from django.test import SimpleTestCase

from scraper.services.html_parser import extract, page_fingerprint
from scraper.services.selector_tester import test_selector
from scraper.tests.helpers import html


class ExtractionTests(SimpleTestCase):
    def test_text_and_attribute(self):
        page = html("listing_page_1.html")
        names = extract(page, ".scholarship-list-card h3 a", multiple=True)
        self.assertEqual(names.match_count, 2)
        self.assertEqual(names.values[0], "RGIT Scholarship for Continuing Students")
        hrefs = extract(
            page,
            ".scholarship-list-card h3 a",
            value_from="attribute",
            attribute_name="href",
            multiple=True,
            base_url="https://search.studyaustralia.gov.au/scholarships?page=1",
        )
        self.assertTrue(hrefs.values[0].startswith("https://search.studyaustralia.gov.au/"))

    def test_relative_url_resolution(self):
        page = html("listing_page_2.html")
        result = extract(
            page,
            "h3 a",
            value_from="attribute",
            attribute_name="href",
            base_url="https://search.studyaustralia.gov.au/scholarships?page=2",
        )
        self.assertEqual(
            result.values[0],
            "https://search.studyaustralia.gov.au/scholarship/ma-and-morley/ccc",
        )

    def test_malformed_html(self):
        result = extract(html("malformed.html"), "h3 a")
        self.assertEqual(result.values[0], "Broken")

    def test_selector_preview(self):
        preview = test_selector(html("listing_page_1.html"), ".scholarship-list-card")
        self.assertEqual(preview["matches"], 2)
        self.assertFalse(preview["error"])

    def test_fingerprint_stable(self):
        first = page_fingerprint(html("listing_page_1.html"), ["a", "b"])
        second = page_fingerprint(html("listing_repeated.html"), ["b", "a"])
        self.assertEqual(first, second)
