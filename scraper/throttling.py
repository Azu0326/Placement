"""Rate-limit Test Page and run creation."""

from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone


class Throttled(Exception):
    pass


def check(key: str, *, limit: int, window_seconds: int) -> None:
    now = int(timezone.now().timestamp())
    bucket = f"scraper-throttle:{key}:{now // window_seconds}"
    count = cache.get(bucket, 0)
    if count >= limit:
        raise Throttled()
    cache.set(bucket, count + 1, window_seconds + 5)
