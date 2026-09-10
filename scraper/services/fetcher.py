"""Choose HTTP or browser rendering, including Auto fallback."""

from __future__ import annotations

from typing import Mapping

from django.conf import settings

from scraper.constants import RENDER_AUTO, RENDER_BROWSER, RENDER_HTTP

from .browser_fetcher import fetch_browser, playwright_available
from .html_parser import looks_like_javascript_app
from .http_fetcher import FetchError, FetchResult, fetch_http


def fetch_page(
    url: str,
    *,
    rendering_mode: str = RENDER_AUTO,
    method: str = "GET",
    timeout: float | None = None,
    wait_after_load_ms: int = 0,
    wait_for_selector: str = "",
    user_agent: str = "",
    headers: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: str | None = None,
    follow_redirects: bool = True,
    verify_tls: bool = True,
) -> FetchResult:
    mode = (rendering_mode or RENDER_AUTO).lower()
    if mode == RENDER_BROWSER:
        return fetch_browser(
            url,
            timeout=timeout,
            wait_after_load_ms=wait_after_load_ms,
            wait_for_selector=wait_for_selector,
            user_agent=user_agent,
            headers=headers,
        )

    result = fetch_http(
        url,
        method=method,
        timeout=timeout,
        headers=headers,
        query=query,
        body=body,
        follow_redirects=follow_redirects,
        verify_tls=verify_tls,
        user_agent=user_agent,
    )
    if mode == RENDER_HTTP:
        return result

    needs_browser = looks_like_javascript_app(result.html, wait_for_selector)
    if wait_for_selector and not needs_browser:
        from .html_parser import SelectorError, parse_html, select

        try:
            needs_browser = not bool(select(parse_html(result.html), wait_for_selector))
        except SelectorError:
            needs_browser = True
    if needs_browser and playwright_available() and getattr(settings, "SCRAPER_BROWSER_ENABLED", True):
        try:
            return fetch_browser(
                url,
                timeout=timeout,
                wait_after_load_ms=wait_after_load_ms,
                wait_for_selector=wait_for_selector,
                user_agent=user_agent,
                headers=headers,
            )
        except FetchError:
            result.javascript_hint = True  # type: ignore[attr-defined]
            return result
    return result
