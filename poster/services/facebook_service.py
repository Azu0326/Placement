"""The only place in Scrapos that talks to the Meta Graph API.

Views, management commands and later poster jobs call this service. None of
them import urllib themselves, and every Graph API error is translated into a
``poster.exceptions`` type so a Facebook error string — or a token — can never
reach a rendered page or a log line.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from ..conf import FacebookPageConfig, get_facebook_config
from ..exceptions import (
    FacebookAuthFailed,
    FacebookNotConfigured,
    FacebookPermissionDenied,
    FacebookPublishFailed,
    FacebookUnavailable,
)

logger = logging.getLogger("scrapos.facebook")

Transport = Callable[[str, str, bytes | None, dict[str, str], int], tuple[int, bytes]]

# Graph API codes that mean the token is gone or was never valid.
_AUTH_CODES = {102, 190, 467}
# Missing permission / cannot perform CREATE_CONTENT on this Page.
_PERMISSION_CODES = {10, 200, 294}
# Transient / capacity / rate-limit style failures.
_UNAVAILABLE_CODES = {1, 2, 4, 17, 32, 613}


@dataclass(frozen=True)
class PublishedPost:
    post_id: str
    page_id: str


@dataclass(frozen=True)
class PageInfo:
    page_id: str
    name: str


@dataclass(frozen=True)
class ManagedPage:
    """A Page the user can publish to.

    ``access_token`` is returned only to the caller (the token-exchange
    command). It is never logged.
    """

    page_id: str
    name: str
    access_token: str
    tasks: tuple[str, ...] = ()


def _default_transport(
    method: str,
    url: str,
    data: bytes | None,
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""
    except urllib.error.URLError as exc:
        raise FacebookUnavailable() from exc
    except TimeoutError as exc:
        raise FacebookUnavailable() from exc


def _graph_error_code(payload: dict[str, Any]) -> int | None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    raw = error.get("code")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _raise_for_graph_error(payload: dict[str, Any], *, status: int) -> None:
    """Map a Graph API error body to an application exception.

    Only the numeric error code is logged. The Facebook ``message`` field is
    discarded so a token fragment or user identifier never reaches the log.
    """
    code = _graph_error_code(payload)
    logger.info("facebook.graph_error status=%s code=%s", status, code)

    if code in _AUTH_CODES or status == 401:
        raise FacebookAuthFailed()
    if code in _PERMISSION_CODES or status == 403:
        raise FacebookPermissionDenied()
    if code in _UNAVAILABLE_CODES or status >= 500:
        raise FacebookUnavailable()
    if status == 400 and not payload.get("id"):
        raise FacebookPublishFailed()
    raise FacebookPublishFailed()


def format_content_message(item: dict[str, Any]) -> str:
    """Turn a Scrapos content row into a Page post body.

    Content models are still demo data; this keeps the wording in one place so
    a later queryset can reuse it.
    """
    title = str(item.get("title") or "").strip()
    if not title:
        raise FacebookPublishFailed("The Facebook post could not be published.")
    return title


class FacebookPageService:
    """Least-privilege wrapper over the Pages publishing endpoints."""

    def __init__(
        self,
        config: FacebookPageConfig | None = None,
        transport: Transport | None = None,
    ):
        self._config = config or get_facebook_config()
        self._transport = transport or _default_transport

    @property
    def config(self) -> FacebookPageConfig:
        return self._config

    @property
    def is_configured(self) -> bool:
        return self._config.is_publish_configured

    def publish(
        self,
        *,
        message: str = "",
        link: str = "",
        image_url: str = "",
        scheduled_unix: int | None = None,
    ) -> PublishedPost:
        """Publish a text, link or photo post as the configured Page."""
        if not self._config.is_publish_configured:
            raise FacebookNotConfigured()

        text = (message or "").strip()
        href = (link or "").strip()
        photo = (image_url or "").strip()
        if not text and not href and not photo:
            raise FacebookPublishFailed()

        if photo:
            return self._publish_photo(
                caption=text, image_url=photo, scheduled_unix=scheduled_unix
            )
        return self._publish_feed(message=text, link=href, scheduled_unix=scheduled_unix)

    def get_page(self) -> PageInfo:
        """Return the configured Page's public name. Never returns a token."""
        if not self._config.is_publish_configured:
            raise FacebookNotConfigured()
        payload = self._request(
            "GET",
            f"/{self._config.page_id}",
            params={"fields": "id,name"},
            token=self._config.page_access_token,
        )
        page_id = str(payload.get("id") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not page_id:
            raise FacebookPublishFailed()
        return PageInfo(page_id=page_id, name=name)

    def exchange_long_lived_user_token(self, short_lived_token: str) -> str:
        """Upgrade a Graph API Explorer user token (~1–2 h) to ~60 days."""
        token = (short_lived_token or "").strip()
        if not token:
            raise FacebookPublishFailed()
        if not self._config.can_exchange_tokens:
            raise FacebookNotConfigured(
                "Facebook app credentials are not configured. Ask an administrator."
            )
        payload = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self._config.app_id,
                "client_secret": self._config.app_secret,
                "fb_exchange_token": token,
            },
            token=None,
        )
        long_lived = str(payload.get("access_token") or "").strip()
        if not long_lived:
            raise FacebookPublishFailed()
        logger.info("facebook.token_exchanged")
        return long_lived

    def list_managed_pages(self, user_access_token: str) -> list[ManagedPage]:
        """Pages the token holder can perform tasks on.

        Each ``ManagedPage.access_token`` is a Page token suitable for
        ``FACEBOOK_PAGE_ACCESS_TOKEN``. It is not logged.
        """
        token = (user_access_token or "").strip()
        if not token:
            raise FacebookPublishFailed()
        payload = self._request(
            "GET",
            "/me/accounts",
            params={"fields": "id,name,access_token,tasks"},
            token=token,
        )
        pages: list[ManagedPage] = []
        for raw in payload.get("data") or ():
            if not isinstance(raw, dict):
                continue
            page_id = str(raw.get("id") or "").strip()
            page_token = str(raw.get("access_token") or "").strip()
            if not page_id or not page_token:
                continue
            tasks = raw.get("tasks") or ()
            pages.append(
                ManagedPage(
                    page_id=page_id,
                    name=str(raw.get("name") or "").strip(),
                    access_token=page_token,
                    tasks=tuple(str(task) for task in tasks),
                )
            )
        logger.info("facebook.pages_listed count=%s", len(pages))
        return pages

    def _publish_feed(
        self,
        *,
        message: str,
        link: str,
        scheduled_unix: int | None,
    ) -> PublishedPost:
        body: dict[str, Any] = {}
        if message:
            body["message"] = message
        if link:
            body["link"] = link
        self._apply_schedule(body, scheduled_unix)
        payload = self._request(
            "POST",
            f"/{self._config.page_id}/feed",
            body=body,
            token=self._config.page_access_token,
        )
        return self._published_from(payload)

    def _publish_photo(
        self,
        *,
        caption: str,
        image_url: str,
        scheduled_unix: int | None,
    ) -> PublishedPost:
        body: dict[str, Any] = {"url": image_url}
        if caption:
            body["caption"] = caption
        self._apply_schedule(body, scheduled_unix)
        payload = self._request(
            "POST",
            f"/{self._config.page_id}/photos",
            body=body,
            token=self._config.page_access_token,
        )
        return self._published_from(payload)

    def _apply_schedule(self, body: dict[str, Any], scheduled_unix: int | None) -> None:
        if scheduled_unix is None:
            return
        if scheduled_unix <= 0:
            raise FacebookPublishFailed()
        body["published"] = "false"
        body["scheduled_publish_time"] = str(int(scheduled_unix))

    def _published_from(self, payload: dict[str, Any]) -> PublishedPost:
        post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
        if not post_id:
            raise FacebookPublishFailed()
        logger.info("facebook.post_published page_id=%s", self._config.page_id)
        return PublishedPost(post_id=post_id, page_id=self._config.page_id)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        token: str | None,
    ) -> dict[str, Any]:
        query = dict(params or {})
        data: bytes | None = None
        headers = {"Accept": "application/json", "User-Agent": "Scrapos/1.0"}

        if method == "GET":
            if token:
                query["access_token"] = token
            url = f"{self._config.graph_base_url}{path}"
            if query:
                url = f"{url}?{urllib.parse.urlencode(query)}"
        else:
            payload = dict(body or {})
            if token:
                payload["access_token"] = token
            url = f"{self._config.graph_base_url}{path}"
            if query:
                url = f"{url}?{urllib.parse.urlencode(query)}"
            data = urllib.parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        try:
            status, raw = self._transport(
                method, url, data, headers, self._config.timeout_seconds
            )
        except FacebookUnavailable:
            raise
        except OSError as exc:
            raise FacebookUnavailable() from exc

        payload = _decode_json(raw)
        if status >= 400 or (isinstance(payload, dict) and payload.get("error")):
            if not isinstance(payload, dict):
                logger.info("facebook.graph_error status=%s code=none", status)
                raise FacebookUnavailable() if status >= 500 else FacebookPublishFailed()
            _raise_for_graph_error(payload, status=status)
        if not isinstance(payload, dict):
            raise FacebookPublishFailed()
        return payload


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FacebookUnavailable() from exc
