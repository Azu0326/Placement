"""HTTP fetching with timeouts, size limits, retries and redirect SSRF checks."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urljoin

import httpx
from django.conf import settings

from .ssrf import RequestPolicyError, ValidatedURL, validate_redirect, validate_url

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message: str, *, status_code: int = 0, blocked: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.blocked = blocked


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    html: str
    duration_ms: int
    rendering_mode: str = "http"
    blocked: bool = False


def _headers(extra: Mapping[str, str] | None, user_agent: str) -> dict[str, str]:
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    for key, value in (extra or {}).items():
        if key.lower() in {"authorization", "cookie", "proxy-authorization"}:
            continue
        headers[key] = value
    return headers


def fetch_http(
    url: str,
    *,
    method: str = "GET",
    timeout: float | None = None,
    headers: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: str | None = None,
    follow_redirects: bool = True,
    verify_tls: bool = True,
    user_agent: str = "",
    max_response_bytes: int | None = None,
    max_retries: int = 2,
) -> FetchResult:
    timeout = timeout if timeout is not None else getattr(settings, "SCRAPER_DEFAULT_TIMEOUT_SECONDS", 20)
    max_response_bytes = max_response_bytes or getattr(settings, "SCRAPER_MAX_RESPONSE_BYTES", 2_000_000)
    user_agent = user_agent or getattr(settings, "SCRAPER_DEFAULT_USER_AGENT", "ScrapOS/1.0")
    validated = validate_url(url)
    started = time.perf_counter()
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return _once(
                validated,
                method=method,
                timeout=timeout,
                headers=_headers(headers, user_agent),
                query=query,
                body=body,
                follow_redirects=follow_redirects,
                verify_tls=verify_tls,
                max_response_bytes=max_response_bytes,
                started=started,
            )
        except FetchError as exc:
            last_error = exc
            if exc.blocked or exc.status_code and exc.status_code not in TRANSIENT_STATUS:
                raise
            if attempt >= max_retries:
                raise
            time.sleep((2**attempt) * 0.25 + random.random() * 0.2)
        except RequestPolicyError:
            raise
    raise last_error or FetchError("The request failed.")


def _once(
    validated: ValidatedURL,
    *,
    method: str,
    timeout: float,
    headers: dict[str, str],
    query: Mapping[str, str] | None,
    body: str | None,
    follow_redirects: bool,
    verify_tls: bool,
    max_response_bytes: int,
    started: float,
) -> FetchResult:
    current = validated
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        verify=verify_tls,
        max_redirects=0,
        headers=headers,
    ) as client:
        hops = 0
        url = current.url
        while True:
            request_kwargs: dict = {"params": query} if query and hops == 0 else {}
            if method.upper() == "POST" and body:
                request_kwargs["content"] = body
            response = client.request(method if hops == 0 else "GET", url, **request_kwargs)
            if response.is_redirect and follow_redirects:
                hops += 1
                if hops > 5:
                    raise FetchError("Too many redirects.", status_code=response.status_code)
                location = response.headers.get("location")
                if not location:
                    raise FetchError("Redirect missing Location.", status_code=response.status_code)
                current = validate_redirect(current, urljoin(url, location))
                url = current.url
                continue
            if response.status_code in {401, 403, 407}:
                raise FetchError(
                    "The site blocked the request.",
                    status_code=response.status_code,
                    blocked=True,
                )
            if response.status_code in TRANSIENT_STATUS:
                raise FetchError(
                    f"Transient HTTP {response.status_code}.",
                    status_code=response.status_code,
                )
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type and "text/plain" not in content_type:
                if "json" not in content_type:
                    raise FetchError(f"Unsupported content type: {content_type or 'unknown'}.", status_code=response.status_code)
            body_bytes = response.content[: max_response_bytes + 1]
            if len(body_bytes) > max_response_bytes:
                raise FetchError("The response exceeded the size limit.", status_code=response.status_code)
            html = body_bytes.decode(response.encoding or "utf-8", errors="replace")
            duration_ms = int((time.perf_counter() - started) * 1000)
            return FetchResult(
                url=validated.url,
                final_url=str(response.url),
                status_code=response.status_code,
                content_type=content_type,
                html=html,
                duration_ms=duration_ms,
            )
