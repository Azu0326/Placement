from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from scraper.services.http_fetcher import FetchError, fetch_http
from scraper.services.ssrf import RequestPolicyError


class HttpFetcherTests(SimpleTestCase):
    @patch("scraper.services.http_fetcher.validate_url")
    @patch("scraper.services.http_fetcher.httpx.Client")
    def test_success(self, client_cls, validate):
        validate.return_value.url = "https://example.com/"
        response = MagicMock()
        response.is_redirect = False
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.content = b"<html>ok</html>"
        response.encoding = "utf-8"
        response.url = "https://example.com/"
        client_cls.return_value.__enter__.return_value.request.return_value = response
        result = fetch_http("https://example.com/", max_retries=0)
        self.assertEqual(result.status_code, 200)
        self.assertIn("ok", result.html)

    @patch("scraper.services.http_fetcher.validate_url")
    @patch("scraper.services.http_fetcher.httpx.Client")
    def test_size_limit(self, client_cls, validate):
        validate.return_value.url = "https://example.com/"
        response = MagicMock()
        response.is_redirect = False
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.content = b"x" * 50
        response.encoding = "utf-8"
        response.url = "https://example.com/"
        client_cls.return_value.__enter__.return_value.request.return_value = response
        with self.assertRaises(FetchError):
            fetch_http("https://example.com/", max_response_bytes=10, max_retries=0)

    @patch("scraper.services.http_fetcher.validate_redirect")
    @patch("scraper.services.http_fetcher.validate_url")
    @patch("scraper.services.http_fetcher.httpx.Client")
    def test_redirect_revalidated(self, client_cls, validate, validate_redirect):
        validate.return_value.url = "https://example.com/"
        validate_redirect.side_effect = RequestPolicyError("private")
        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.status_code = 302
        redirect.headers = {"location": "http://127.0.0.1/"}
        client_cls.return_value.__enter__.return_value.request.return_value = redirect
        with self.assertRaises(RequestPolicyError):
            fetch_http("https://example.com/", max_retries=0)
