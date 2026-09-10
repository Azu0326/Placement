"""Normalize extracted values to the configured data type."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from scraper.constants import (
    DATA_BOOLEAN,
    DATA_CURRENCY,
    DATA_DATE,
    DATA_DATETIME,
    DATA_DECIMAL,
    DATA_EMAIL,
    DATA_HTML,
    DATA_INTEGER,
    DATA_JSON,
    DATA_LIST,
    DATA_LONG_TEXT,
    DATA_TEXT,
    DATA_URL,
)

TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}


class TypeError_(ValueError):
    pass


def _one(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def to_text(value: Any) -> str | None:
    item = _one(value)
    if item is None:
        return None
    return str(item)


def to_integer(value: Any) -> int | None:
    item = _one(value)
    if item in (None, ""):
        return None
    if isinstance(item, bool):
        return int(item)
    if isinstance(item, int):
        return item
    try:
        return int(str(item).replace(",", "").split(".")[0])
    except ValueError as exc:
        raise TypeError_(f"Cannot convert {item!r} to integer.") from exc


def to_decimal(value: Any) -> str | None:
    item = _one(value)
    if item in (None, ""):
        return None
    try:
        return str(Decimal(str(item).replace(",", "")))
    except InvalidOperation as exc:
        raise TypeError_(f"Cannot convert {item!r} to decimal.") from exc


def to_boolean(value: Any) -> bool | None:
    item = _one(value)
    if item in (None, ""):
        return None
    if isinstance(item, bool):
        return item
    text = str(item).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise TypeError_(f"Cannot convert {item!r} to boolean.")


def to_url(value: Any) -> str | None:
    item = to_text(value)
    if not item:
        return None
    parsed = urlparse(item)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TypeError_(f"Not a valid URL: {item!r}.")
    return item


def to_email(value: Any) -> str | None:
    item = to_text(value)
    if not item:
        return None
    if "@" not in item or "." not in item.split("@")[-1]:
        raise TypeError_(f"Not a valid email: {item!r}.")
    return item.strip()


def to_datetime(value: Any) -> str | None:
    item = _one(value)
    if item in (None, ""):
        return None
    if isinstance(item, datetime):
        return item.isoformat()
    text = str(item).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.replace("Z", ""), fmt.replace("Z", "")).isoformat()
        except ValueError:
            continue
    return text


def to_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise TypeError_("Value is not valid JSON.") from exc
    return value


def to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


CONVERTERS = {
    DATA_TEXT: to_text,
    DATA_LONG_TEXT: to_text,
    DATA_HTML: to_text,
    DATA_INTEGER: to_integer,
    DATA_DECIMAL: to_decimal,
    DATA_CURRENCY: to_decimal,
    DATA_BOOLEAN: to_boolean,
    DATA_DATE: to_datetime,
    DATA_DATETIME: to_datetime,
    DATA_URL: to_url,
    DATA_EMAIL: to_email,
    DATA_JSON: to_json,
    DATA_LIST: to_list,
}


def normalize(value: Any, data_type: str, *, multiple: bool = False) -> Any:
    if multiple or data_type == DATA_LIST:
        items = value if isinstance(value, list) else ([] if value in (None, "") else [value])
        converter = CONVERTERS.get(DATA_TEXT if data_type == DATA_LIST else data_type, to_text)
        out = []
        for item in items:
            converted = converter(item)
            if converted not in (None, ""):
                out.append(converted)
        return out
    converter = CONVERTERS.get(data_type, to_text)
    return converter(value)
