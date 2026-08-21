"""Safe, explicit transform registry. Never evaluates user code."""

from __future__ import annotations

import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_CURRENCY_RE = re.compile(r"[^\d.\-]")
_MAX_REGEX_LENGTH = 200
_REGEX_TIMEOUT_STEPS = 50_000


class TransformError(ValueError):
    pass


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _map(value: Any, fn: Callable[[Any], Any]) -> Any:
    if isinstance(value, list):
        return [fn(item) for item in value]
    return fn(value)


def trim(value: Any, **_kwargs) -> Any:
    return _map(value, lambda item: item.strip() if isinstance(item, str) else item)


def normalize_whitespace(value: Any, **_kwargs) -> Any:
    return _map(value, lambda item: re.sub(r"\s+", " ", item).strip() if isinstance(item, str) else item)


def lowercase(value: Any, **_kwargs) -> Any:
    return _map(value, lambda item: item.lower() if isinstance(item, str) else item)


def uppercase(value: Any, **_kwargs) -> Any:
    return _map(value, lambda item: item.upper() if isinstance(item, str) else item)


def title_case(value: Any, **_kwargs) -> Any:
    return _map(value, lambda item: item.title() if isinstance(item, str) else item)


def remove_html(value: Any, **_kwargs) -> Any:
    def _strip(item: Any) -> Any:
        if not isinstance(item, str):
            return item
        return BeautifulSoup(item, "lxml").get_text(" ", strip=True)

    return _map(value, _strip)


def resolve_absolute_url(value: Any, *, base_url: str = "", **_kwargs) -> Any:
    return _map(value, lambda item: urljoin(base_url, item) if isinstance(item, str) and item else item)


def remove_prefix(value: Any, *, prefix: str = "", **_kwargs) -> Any:
    return _map(
        value,
        lambda item: item[len(prefix) :] if isinstance(item, str) and item.startswith(prefix) else item,
    )


def remove_suffix(value: Any, *, suffix: str = "", **_kwargs) -> Any:
    return _map(
        value,
        lambda item: item[: -len(suffix)] if isinstance(item, str) and suffix and item.endswith(suffix) else item,
    )


def replace_text(value: Any, *, find: str = "", replace: str = "", **_kwargs) -> Any:
    return _map(value, lambda item: item.replace(find, replace) if isinstance(item, str) else item)


def _safe_regex(pattern: str) -> re.Pattern[str]:
    if not pattern or len(pattern) > _MAX_REGEX_LENGTH:
        raise TransformError("The regular expression is missing or too long.")
    if any(token in pattern for token in (r"(?!", r"(?=", r"(?<=", r"(?<!")):
        raise TransformError("Lookaround expressions are not allowed.")
    if pattern.count("*") + pattern.count("+") + pattern.count("{") > 8:
        raise TransformError("The regular expression is too complex.")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise TransformError(f"Invalid regular expression: {exc}") from exc
    return compiled


def regex_capture(value: Any, *, pattern: str = "", group: int = 1, **_kwargs) -> Any:
    compiled = _safe_regex(pattern)

    def _capture(item: Any) -> Any:
        if not isinstance(item, str):
            return item
        match = compiled.search(item)
        if not match:
            return ""
        if match.lastindex and group <= match.lastindex:
            return match.group(group) or ""
        return match.group(0)

    return _map(value, _capture)


def parse_integer(value: Any, **_kwargs) -> Any:
    def _parse(item: Any) -> Any:
        if item in (None, ""):
            return None
        digits = re.sub(r"[^\d\-]", "", str(item))
        if digits in {"", "-"}:
            return None
        return int(digits)

    return _map(value, _parse)


def parse_decimal(value: Any, **_kwargs) -> Any:
    def _parse(item: Any) -> Any:
        if item in (None, ""):
            return None
        cleaned = _CURRENCY_RE.sub("", str(item))
        if cleaned in {"", ".", "-"}:
            return None
        try:
            return str(Decimal(cleaned))
        except InvalidOperation:
            return None

    return _map(value, _parse)


def parse_currency(value: Any, **_kwargs) -> Any:
    return parse_decimal(value)


def parse_date(value: Any, *, formats: list[str] | None = None, **_kwargs) -> Any:
    candidates = formats or [
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    def _parse(item: Any) -> Any:
        if not item:
            return None
        text = str(item).strip()
        for fmt in candidates:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return text

    return _map(value, _parse)


def join_values(value: Any, *, delimiter: str = ", ", **_kwargs) -> Any:
    items = [str(item) for item in _as_list(value) if item not in (None, "")]
    return delimiter.join(items)


def split_value(value: Any, *, delimiter: str = ",", **_kwargs) -> Any:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(split_value(item, delimiter=delimiter))
        return out
    if not isinstance(value, str):
        return [] if value is None else [value]
    return [part.strip() for part in value.split(delimiter) if part.strip()]


def deduplicate_list(value: Any, **_kwargs) -> Any:
    seen: set[str] = set()
    out = []
    for item in _as_list(value):
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def default_value(value: Any, *, fallback: Any = None, **_kwargs) -> Any:
    if value in (None, "", []):
        return fallback
    return value


def unescape(value: Any, **_kwargs) -> Any:
    return _map(value, lambda item: html.unescape(item) if isinstance(item, str) else item)


REGISTRY: dict[str, Callable[..., Any]] = {
    "trim": trim,
    "normalize_whitespace": normalize_whitespace,
    "lowercase": lowercase,
    "uppercase": uppercase,
    "title_case": title_case,
    "remove_html": remove_html,
    "resolve_absolute_url": resolve_absolute_url,
    "remove_prefix": remove_prefix,
    "remove_suffix": remove_suffix,
    "replace_text": replace_text,
    "regex_capture": regex_capture,
    "parse_integer": parse_integer,
    "parse_decimal": parse_decimal,
    "parse_currency": parse_currency,
    "parse_date": parse_date,
    "join_values": join_values,
    "split_value": split_value,
    "deduplicate_list": deduplicate_list,
    "default_value": default_value,
    "unescape": unescape,
}


def apply_pipeline(value: Any, steps: list[Any] | None, *, base_url: str = "") -> Any:
    current = value
    for step in steps or []:
        if isinstance(step, str):
            name, kwargs = step, {}
        elif isinstance(step, dict):
            name = step.get("name") or step.get("transform") or ""
            kwargs = {k: v for k, v in step.items() if k not in {"name", "transform"}}
        else:
            raise TransformError("Each transform must be a name or an object.")
        fn = REGISTRY.get(name)
        if fn is None:
            raise TransformError(f"Unknown transform: {name}.")
        current = fn(current, base_url=base_url, **kwargs)
    return current
