"""Instagram comment moderation via the Meta Graph API.

Create, list, reply to and delete comments on media owned by the Instagram
Professional account linked to the configured Facebook Page. Tokens are never
logged. Graph errors reuse the Facebook exception types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from poster.conf import get_facebook_config
from poster.exceptions import FacebookPublishFailed, InstagramNotConfigured
from poster.services.facebook_service import FacebookPageService

logger = logging.getLogger("scrapos.facebook")

COMMENT_FIELDS = "id,text,username,timestamp,like_count,hidden"
MEDIA_FIELDS = "id,caption,timestamp,permalink,media_type"


@dataclass(frozen=True)
class InstagramMedia:
    media_id: str
    caption: str
    permalink: str
    timestamp: str
    media_type: str


@dataclass(frozen=True)
class InstagramComment:
    comment_id: str
    text: str
    username: str
    timestamp: str


def _comment_from(payload: dict[str, Any]) -> InstagramComment:
    comment_id = str(payload.get("id") or "").strip()
    if not comment_id:
        raise FacebookPublishFailed("The Instagram comment could not be published.")
    return InstagramComment(
        comment_id=comment_id,
        text=str(payload.get("text") or ""),
        username=str(payload.get("username") or ""),
        timestamp=str(payload.get("timestamp") or ""),
    )


class InstagramCommentService:
    """Least-privilege wrapper over IG Media / IG Comment endpoints."""

    def __init__(self, config=None, transport=None):
        self._page = FacebookPageService(config=config, transport=transport)

    @property
    def config(self):
        return self._page.config

    def is_configured(self) -> bool:
        return self.config.is_instagram_comments_configured

    def account_id(self) -> str:
        if not self.config.page_access_token:
            raise InstagramNotConfigured()
        if self.config.instagram_account_id:
            return self.config.instagram_account_id
        if not self.config.page_id:
            raise InstagramNotConfigured()
        payload = self._page._request(
            "GET",
            f"/{self.config.page_id}",
            params={"fields": "instagram_business_account"},
            token=self.config.page_access_token,
        )
        account = payload.get("instagram_business_account") or {}
        ig_id = str(account.get("id") or "").strip()
        if not ig_id:
            raise InstagramNotConfigured(
                "No Instagram Professional account is linked to this Facebook Page."
            )
        return ig_id

    def list_media(self, *, limit: int = 10) -> list[InstagramMedia]:
        ig_id = self.account_id()
        payload = self._page._request(
            "GET",
            f"/{ig_id}/media",
            params={"fields": MEDIA_FIELDS, "limit": str(max(1, min(limit, 50)))},
            token=self.config.page_access_token,
        )
        media: list[InstagramMedia] = []
        for raw in payload.get("data") or ():
            if not isinstance(raw, dict):
                continue
            media_id = str(raw.get("id") or "").strip()
            if not media_id:
                continue
            media.append(
                InstagramMedia(
                    media_id=media_id,
                    caption=str(raw.get("caption") or ""),
                    permalink=str(raw.get("permalink") or ""),
                    timestamp=str(raw.get("timestamp") or ""),
                    media_type=str(raw.get("media_type") or ""),
                )
            )
        logger.info("instagram.media_listed count=%s", len(media))
        return media

    def list_comments(self, media_id: str) -> list[InstagramComment]:
        media_id = (media_id or "").strip()
        if not media_id:
            raise FacebookPublishFailed("The Instagram comment could not be published.")
        self._require_token()
        payload = self._page._request(
            "GET",
            f"/{media_id}/comments",
            params={"fields": COMMENT_FIELDS},
            token=self.config.page_access_token,
        )
        comments = [
            _comment_from(raw)
            for raw in payload.get("data") or ()
            if isinstance(raw, dict) and raw.get("id")
        ]
        logger.info("instagram.comments_listed count=%s", len(comments))
        return comments

    def create_comment(self, media_id: str, message: str) -> InstagramComment:
        """Post a comment as the Professional account on its own media."""
        return self._post_message(f"/{(media_id or '').strip()}/comments", message)

    def reply_to_comment(self, comment_id: str, message: str) -> InstagramComment:
        """Reply to a top-level comment. Replies to replies attach to the parent."""
        return self._post_message(f"/{(comment_id or '').strip()}/replies", message)

    def delete_comment(self, comment_id: str) -> None:
        comment_id = (comment_id or "").strip()
        if not comment_id:
            raise FacebookPublishFailed("The Instagram comment could not be published.")
        self._require_token()
        self._page._request(
            "DELETE",
            f"/{comment_id}",
            token=self.config.page_access_token,
        )
        logger.info("instagram.comment_deleted")

    def _post_message(self, path: str, message: str) -> InstagramComment:
        text = (message or "").strip()
        target = path.strip("/")
        if not text or not target:
            raise FacebookPublishFailed("The Instagram comment could not be published.")
        self._require_token()
        payload = self._page._request(
            "POST",
            path,
            body={"message": text},
            token=self.config.page_access_token,
        )
        logger.info("instagram.comment_written")
        return _comment_from(payload)

    def _require_token(self) -> None:
        if not self.config.page_access_token:
            raise InstagramNotConfigured()


def get_instagram_comment_service() -> InstagramCommentService:
    return InstagramCommentService(get_facebook_config())
