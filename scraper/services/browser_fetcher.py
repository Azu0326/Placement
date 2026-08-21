"""Optional Playwright fetcher. HTTP mode remains the default."""

from __future__ import annotations

import time
from typing import Mapping

from django.conf import settings

from .http_fetcher import FetchError, FetchResult
from .ssrf import validate_url


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def fetch_browser(
    url: str,
    *,
    timeout: float | None = None,
    wait_after_load_ms: int = 0,
    wait_for_selector: str = "",
    user_agent: str = "",
    headers: Mapping[str, str] | None = None,
) -> FetchResult:
    if not playwright_available():
        raise FetchError("Browser rendering is not installed on this server.")

    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    timeout = timeout if timeout is not None else getattr(settings, "SCRAPER_DEFAULT_TIMEOUT_SECONDS", 20)
    user_agent = user_agent or getattr(settings, "SCRAPER_DEFAULT_USER_AGENT", "ScrapOS/1.0")
    validated = validate_url(url)
    started = time.perf_counter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = None
        page = None
        try:
            extra = {
                key: value
                for key, value in (headers or {}).items()
                if key.lower() not in {"authorization", "cookie", "proxy-authorization"}
            }
            context = browser.new_context(user_agent=user_agent, extra_http_headers=extra or None)
            context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"media", "font"}
                else route.continue_(),
            )
            page = context.new_page()
            response = page.goto(validated.url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=int(timeout * 1000))
            if wait_after_load_ms:
                page.wait_for_timeout(min(int(wait_after_load_ms), 10_000))
            html = page.content()
            final_url = page.url
            validate_url(final_url)
            status = response.status if response else 0
            if status in {401, 403}:
                raise FetchError("The site blocked the request.", status_code=status, blocked=True)
            return FetchResult(
                url=validated.url,
                final_url=final_url,
                status_code=status,
                content_type="text/html",
                html=html,
                duration_ms=int((time.perf_counter() - started) * 1000),
                rendering_mode="browser",
            )
        except PlaywrightTimeout as exc:
            raise FetchError("The browser timed out waiting for the page.") from exc
        finally:
            if page:
                page.close()
            if context:
                context.close()
            browser.close()
