from unittest.mock import patch

from django.test import TestCase, override_settings

from scraper.constants import RUN_CANCELLED, RUN_COMPLETED, RUN_QUEUED
from scraper.models import ScrapedRecord
from scraper.services.exporters import generate_csv, generate_sqlite
from scraper.services.http_fetcher import FetchResult
from scraper.services.orchestrator import execute_run, request_cancel
from scraper.tests.helpers import configure_listing_job, html, make_job, make_user, queued_run


def fake_fetch(url, **kwargs):
    if "page=2" in url:
        body = html("listing_page_2.html")
    elif "page=3" in url or "empty" in url:
        body = html("listing_empty.html")
    elif "/scholarship/" in url and "scholarships?" not in url:
        body = html("detail_page.html")
    else:
        body = html("listing_page_1.html")
    return FetchResult(url=url, final_url=url, status_code=200, content_type="text/html", html=body, duration_ms=5)


@override_settings(SCRAPER_INLINE_WORKER=False, SCRAPER_DEFAULT_DELAY_SECONDS=0)
class IntegrationTests(TestCase):
    def setUp(self):
        self.user = make_user("editor.one")
        self.job = configure_listing_job(make_job(self.user, name="Study Australia Scholarships"))

    @patch("scraper.services.orchestrator.fetch_page", side_effect=fake_fetch)
    def test_two_page_run_and_exports(self, _mock):
        run = queued_run(self.job, self.user)
        execute_run(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, RUN_COMPLETED)
        self.assertGreaterEqual(run.pages_completed, 2)
        self.assertEqual(run.records_created, 3)
        urls = list(run.records.values_list("detail_url", flat=True))
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(u.startswith("https://") for u in urls if u))
        self.assertTrue(run.records.filter(normalized_data__scholarship_name__isnull=False).exists())

        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "out.csv"
            sqlite_path = Path(tmp) / "out.sqlite3"
            csv_count = generate_csv(run, csv_path)
            sqlite_count = generate_sqlite(run, sqlite_path)
            self.assertEqual(csv_count, sqlite_count)
            self.assertGreater(csv_count, 0)
            text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("scholarship_name", text)
            import sqlite3

            conn = sqlite3.connect(sqlite_path)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("select count(*) from results").fetchone()[0], sqlite_count)
            conn.close()

    @patch("scraper.services.orchestrator.fetch_page", side_effect=fake_fetch)
    def test_repeated_page_stops(self, mock_fetch):
        def same_page(url, **kwargs):
            return FetchResult(url=url, final_url=url, status_code=200, content_type="text/html", html=html("listing_page_1.html"), duration_ms=1)

        mock_fetch.side_effect = same_page
        run = queued_run(self.job, self.user)
        execute_run(run.id)
        run.refresh_from_db()
        self.assertLessEqual(run.pages_attempted, 3)
        self.assertEqual(run.records.filter(unique_key__gt="").count(), run.records.values("unique_key").distinct().count())

    @patch("scraper.services.orchestrator.fetch_page", side_effect=fake_fetch)
    def test_cancellation_stops_requests(self, mock_fetch):
        run = queued_run(self.job, self.user)
        request_cancel(run)
        execute_run(run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, RUN_CANCELLED)
        self.assertEqual(mock_fetch.call_count, 0)

    def test_filename_safety(self):
        from scraper.services.exporters import _safe_filename

        name = _safe_filename("../evil job", "11111111-2222", "csv")
        self.assertNotIn("..", name)
        self.assertTrue(name.endswith(".csv"))
