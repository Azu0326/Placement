"""Application-level Facebook publishing errors.

Graph API / network failures are translated into these types before they leave
``poster.services.facebook_service``, so callers never see a raw Facebook
error string and never risk logging a Page access token.
"""

from __future__ import annotations


class FacebookPublishError(Exception):
    """Base class for every Facebook Page publishing failure."""


class FacebookNotConfigured(FacebookPublishError):
    """Page id or Page access token is missing, so publishing cannot start."""

    def __init__(
        self,
        message: str = "Facebook publishing is not configured. Ask an administrator to connect a Page.",
    ):
        super().__init__(message)


class FacebookAuthFailed(FacebookPublishError):
    """The Page access token was rejected or has expired."""

    def __init__(
        self,
        message: str = "Facebook access has expired. Reconnect the Page to resume publishing.",
    ):
        super().__init__(message)


class FacebookPermissionDenied(FacebookPublishError):
    """The token is valid but cannot perform CREATE_CONTENT on this Page."""

    def __init__(
        self,
        message: str = "Scrapos is not permitted to publish to this Facebook Page.",
    ):
        super().__init__(message)


class FacebookUnavailable(FacebookPublishError):
    """Graph API could not be reached, or returned a server-side / rate-limit failure."""

    def __init__(
        self,
        message: str = "Facebook is temporarily unavailable. Please try again shortly.",
    ):
        super().__init__(message)


class FacebookPublishFailed(FacebookPublishError):
    """The post was rejected for an expected, reportable reason."""

    def __init__(self, message: str = "The Facebook post could not be published."):
        super().__init__(message)
