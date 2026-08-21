"""Render ``{{variable}}`` placeholders in URL templates."""

from __future__ import annotations

import re
from typing import Any, Mapping

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class TemplateError(ValueError):
    """The URL template cannot be rendered."""


def placeholders(template: str) -> list[str]:
    return PLACEHOLDER_RE.findall(template or "")


def render(template: str, values: Mapping[str, Any]) -> str:
    if not template:
        raise TemplateError("A URL template is required.")
    missing = [name for name in placeholders(template) if name not in values or values[name] in (None, "")]
    if missing:
        raise TemplateError(f"Missing variables: {', '.join(missing)}.")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(values[name])

    return PLACEHOLDER_RE.sub(replace, template)


def infer_page_template(url: str) -> str | None:
    """Turn ``?page=1`` into ``?page={{page}}`` when the query is a simple counter."""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    out = []
    for key, value in pairs:
        if key.lower() == "page" and value.isdigit():
            out.append((key, "{{page}}"))
            replaced = True
        else:
            out.append((key, value))
    if not replaced:
        return None
    query = urlencode(out, safe="{}")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))
