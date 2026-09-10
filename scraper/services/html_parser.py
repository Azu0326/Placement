"""CSS selector extraction over sanitized or raw fetched HTML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, FeatureNotFound, SoupStrainer
from bs4.element import Tag

from scraper.constants import VALUE_ATTRIBUTE, VALUE_EXISTS, VALUE_INNER_HTML, VALUE_TEXT


class SelectorError(ValueError):
    pass


@dataclass
class Extraction:
    values: list[Any]
    match_count: int
    raw_html: list[str] = field(default_factory=list)
    error: str = ""


def parse_html(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html or "", "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html or "", "html.parser")


def select(soup: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    if not selector or not selector.strip():
        raise SelectorError("A CSS selector is required.")
    try:
        return list(soup.select(selector))
    except Exception as exc:  # soupsieve raises various selector errors
        raise SelectorError(f"Invalid selector: {exc}") from exc


def extract_from_element(
    element: Tag,
    *,
    value_from: str = VALUE_TEXT,
    attribute_name: str = "",
    base_url: str = "",
) -> Any:
    if value_from == VALUE_EXISTS:
        return True
    if value_from == VALUE_ATTRIBUTE:
        if not attribute_name:
            raise SelectorError("An attribute name is required.")
        raw = element.get(attribute_name)
        if raw is None:
            return None
        if isinstance(raw, list):
            raw = " ".join(raw)
        if attribute_name.lower() in {"href", "src"} and raw and base_url:
            return urljoin(base_url, raw)
        return raw
    if value_from == VALUE_INNER_HTML:
        return "".join(str(child) for child in element.children)
    return element.get_text(" ", strip=True)


def extract(
    html: str | BeautifulSoup | Tag,
    selector: str,
    *,
    value_from: str = VALUE_TEXT,
    attribute_name: str = "",
    multiple: bool = False,
    base_url: str = "",
    include_html: bool = False,
) -> Extraction:
    root = html if isinstance(html, (BeautifulSoup, Tag)) else parse_html(html)
    try:
        matches = select(root, selector)
    except SelectorError as exc:
        return Extraction(values=[], match_count=0, error=str(exc))

    values: list[Any] = []
    snippets: list[str] = []
    for match in matches:
        values.append(
            extract_from_element(
                match,
                value_from=value_from,
                attribute_name=attribute_name,
                base_url=base_url,
            )
        )
        if include_html:
            snippets.append(str(match)[:2000])

    if not multiple:
        values = values[:1]
        snippets = snippets[:1]
    return Extraction(values=values, match_count=len(matches), raw_html=snippets)


def page_fingerprint(html: str, identifiers: list[str] | None = None) -> str:
    import hashlib

    if identifiers:
        payload = "\n".join(sorted(identifiers))
    else:
        soup = parse_html(html)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        payload = " ".join(soup.get_text(" ", strip=True).split())[:8000]
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def looks_like_javascript_app(html: str, selector: str = "") -> bool:
    soup = parse_html(html)
    text = soup.get_text(" ", strip=True)
    scripts = soup.find_all("script")
    root = soup.select_one("#app, #root, [data-reactroot]")
    if selector:
        try:
            if select(soup, selector):
                return False
        except SelectorError:
            pass
    if root and len(text) < 400:
        return True
    if scripts and len(text) < 200:
        return True
    return False
