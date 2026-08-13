"""Login throttling.

Both authentication providers go through the same throttle, so the bootstrap
account gets no easier a ride than a Cognito user. Counting is per username and
per source address: the username limit stops a targeted password guess, the
address limit stops someone spraying many usernames from one host.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .exceptions import TooManyAttempts
from .models import LoginAttempt


def _window_start():
    minutes = getattr(settings, "SCRAPOS_LOGIN_THROTTLE_WINDOW_MINUTES", 15)
    return timezone.now() - timezone.timedelta(minutes=minutes)


def _normalise(username: str) -> str:
    return (username or "").strip().lower()[:150]


def check(username: str, ip_address: str | None) -> None:
    """Raise :class:`TooManyAttempts` if either limit is already exhausted."""
    if not getattr(settings, "SCRAPOS_LOGIN_THROTTLE_ENABLED", True):
        return

    per_user = getattr(settings, "SCRAPOS_LOGIN_THROTTLE_MAX_PER_USER", 5)
    per_ip = getattr(settings, "SCRAPOS_LOGIN_THROTTLE_MAX_PER_IP", 20)
    since = _window_start()

    recent = LoginAttempt.objects.filter(created_at__gte=since, successful=False)

    if recent.filter(username=_normalise(username)).count() >= per_user:
        raise TooManyAttempts()

    if ip_address and recent.filter(ip_address=ip_address).count() >= per_ip:
        raise TooManyAttempts()


def record_failure(username: str, ip_address: str | None) -> None:
    LoginAttempt.objects.create(
        username=_normalise(username),
        ip_address=ip_address if _is_storable(ip_address) else None,
        successful=False,
    )


def record_success(username: str, ip_address: str | None) -> None:
    """Log the success and clear the user's failures so they start clean."""
    LoginAttempt.objects.create(
        username=_normalise(username),
        ip_address=ip_address if _is_storable(ip_address) else None,
        successful=True,
    )
    LoginAttempt.objects.filter(username=_normalise(username), successful=False).delete()


def purge(older_than_days: int = 7) -> int:
    """Drop stale rows. Called opportunistically so the table cannot grow forever."""
    cutoff = timezone.now() - timezone.timedelta(days=older_than_days)
    deleted, _ = LoginAttempt.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def _is_storable(value: str | None) -> bool:
    if not value:
        return False
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True
