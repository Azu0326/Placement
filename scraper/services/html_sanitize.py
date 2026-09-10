"""Sanitize HTML previews so scraped scripts never execute in the UI."""

from __future__ import annotations

import bleach

ALLOWED_TAGS = [
    "a",
    "abbr",
    "article",
    "aside",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "div",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "section",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
]
ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "img": ["src", "alt"],
    "*": ["class", "id"],
}


def sanitize_html(html: str, *, max_chars: int = 200_000) -> str:
    cleaned = bleach.clean(
        html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
        protocols=["http", "https"],
    )
    if len(cleaned) > max_chars:
        return cleaned[:max_chars] + "\n<!-- truncated -->"
    return cleaned


def escape_text(value: str) -> str:
    return bleach.clean(value or "", tags=[], strip=True)
