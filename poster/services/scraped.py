"""Map a scraped record onto a Facebook Page post.

Field names come from each job's ScrapeField list, so this looks up common
keys (scholarship_name, title, detail_url, image, …) rather than a fixed
schema. Tokens are never read here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from poster.exceptions import FacebookPublishFailed

MESSAGE_KEYS = (
    "scholarship_name",
    "title",
    "name",
    "heading",
    "headline",
    "message",
    "text",
    "caption",
)
DESCRIPTION_KEYS = ("description", "summary", "body")
LINK_KEYS = ("detail_url", "url", "link", "href", "source_url")
IMAGE_KEYS = ("image", "image_url", "photo", "thumbnail", "img", "picture")


@dataclass(frozen=True)
class ScrapedFacebookPost:
    message: str
    link: str
    image_url: str
    record_id: str = ""

    @property
    def uses_photo(self) -> bool:
        return bool(self.image_url)


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _as_text(data.get(key))
        if text:
            return text
    return ""


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _first_url(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    text = _first_text(data, keys)
    return text if text and _is_http_url(text) else ""


def payload_from_scraped(
    normalized: dict[str, Any] | None,
    *,
    detail_url: str = "",
    source_url: str = "",
    include_image: bool = False,
    record_id: str = "",
) -> ScrapedFacebookPost:
    """Build a Page post from one scraped row.

    Default is a feed post (message + link). Pass ``include_image=True`` to
    publish a photo when the row has a public image URL.
    """
    data = dict(normalized or {})
    title = _first_text(data, MESSAGE_KEYS)
    description = _first_text(data, DESCRIPTION_KEYS)
    if title and description and description != title:
        message = f"{title}\n\n{description}"
    else:
        message = title or description

    link = (detail_url or "").strip()
    if not (link and _is_http_url(link)):
        link = _first_url(data, LINK_KEYS)
    if not link and source_url and _is_http_url(source_url.strip()):
        link = source_url.strip()

    image_url = _first_url(data, IMAGE_KEYS) if include_image else ""
    if image_url and link:
        # Photos edge cannot also attach a link preview. Keep the source URL
        # in the caption so the post still points back at the scraped page.
        if link not in message:
            message = f"{message}\n\n{link}".strip()
        link = ""

    if not message and not link and not image_url:
        raise FacebookPublishFailed()
    return ScrapedFacebookPost(
        message=message,
        link=link,
        image_url=image_url,
        record_id=record_id,
    )


def payload_from_record(record, *, include_image: bool = False) -> ScrapedFacebookPost:
    data = record.normalized_data or record.raw_data or {}
    return payload_from_scraped(
        data,
        detail_url=getattr(record, "detail_url", "") or "",
        source_url=getattr(record, "source_url", "") or "",
        include_image=include_image,
        record_id=str(getattr(record, "id", "") or ""),
    )
