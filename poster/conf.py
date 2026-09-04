"""Centralised access to Facebook Page publishing configuration.

Nothing outside this module reads the Facebook settings directly. Tokens stay
on the server: they are never passed to templates, audit metadata, or logs.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


def _setting(name: str, default: str = "") -> str:
    return (getattr(settings, name, default) or "").strip()


@dataclass(frozen=True)
class FacebookPageConfig:
    """Credentials needed to publish as a Facebook Page.

    ``page_access_token`` and ``app_secret`` never leave the server. A Page
    token is enough to publish; the app id/secret are only used when exchanging
    a short-lived user token for a long-lived one.
    """

    page_id: str
    page_access_token: str
    app_id: str
    app_secret: str
    graph_api_version: str
    timeout_seconds: int

    @property
    def is_publish_configured(self) -> bool:
        """True when a feed or photo post can be attempted."""
        return bool(self.page_id and self.page_access_token)

    @property
    def can_exchange_tokens(self) -> bool:
        """True when a short-lived user token can be upgraded."""
        return bool(self.app_id and self.app_secret)

    @property
    def graph_base_url(self) -> str:
        version = self.graph_api_version.lstrip("/")
        if not version.startswith("v"):
            version = f"v{version}"
        return f"https://graph.facebook.com/{version}"


def get_facebook_config() -> FacebookPageConfig:
    timeout = getattr(settings, "FACEBOOK_GRAPH_TIMEOUT_SECONDS", 20)
    try:
        timeout_seconds = int(timeout)
    except (TypeError, ValueError):
        timeout_seconds = 20
    return FacebookPageConfig(
        page_id=_setting("FACEBOOK_PAGE_ID"),
        page_access_token=_setting("FACEBOOK_PAGE_ACCESS_TOKEN"),
        app_id=_setting("FACEBOOK_APP_ID"),
        app_secret=_setting("FACEBOOK_APP_SECRET"),
        graph_api_version=_setting("FACEBOOK_GRAPH_API_VERSION", "v22.0") or "v22.0",
        timeout_seconds=timeout_seconds,
    )
