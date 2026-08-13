"""Audit trail and structured security logging.

Every security-relevant event goes through :func:`record`, which writes an
``AuditEvent`` row and emits a structured log line. Both are scrubbed: values
whose key looks like a credential are dropped rather than redacted, so a typo
in a call site cannot leak a secret into the database or CloudWatch.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("scrapos.audit")

# Authentication
LOGIN_SUCCESS = "authentication_success"
LOGIN_FAILURE = "authentication_failure"
BOOTSTRAP_LOGIN = "bootstrap_admin_login"
LOGOUT = "logout"
LOGIN_THROTTLED = "authentication_throttled"
PERMISSION_DENIED = "permission_denied"
SESSION_REVOKED = "session_revoked"
COGNITO_REQUEST_FAILURE = "cognito_request_failure"

# Identity linking
IDENTITY_LINKED = "identity_linked"
IDENTITY_DUPLICATE_DETECTED = "identity_duplicate_detected"

# Administration
USER_CREATED = "user_created"
USER_ENABLED = "user_enabled"
USER_DISABLED = "user_disabled"
USER_ROLE_CHANGED = "user_role_changed"
PASSWORD_RESET_INITIATED = "password_reset_initiated"
SETTINGS_CHANGED = "settings_changed"

#: Substrings that mark a metadata key as unsafe to persist.
_FORBIDDEN_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "session_key",
    "access_key",
    "private",
    "hash",
)

_MAX_VALUE_LENGTH = 500


def scrub(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop anything credential-shaped and truncate the rest."""
    if not metadata:
        return {}
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            continue
        if isinstance(value, (dict, list, tuple)):
            value = str(value)
        if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
            value = value[:_MAX_VALUE_LENGTH] + "…"
        clean[str(key)] = value
    return clean


def client_ip(request) -> str | None:
    """Client address behind the ALB.

    ``X-Forwarded-For`` is appended to by each proxy, so the left-most entry is
    the original client. It is only trusted because every route to the
    container goes through the ALB.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate
    return request.META.get("REMOTE_ADDR") or None


def record(
    action: str,
    *,
    request=None,
    actor: str = "",
    actor_auth_source: str = "",
    target: str = "",
    ip_address: str | None = None,
    level: int = logging.INFO,
    **metadata: Any,
) -> None:
    """Write one audit row and one structured log line.

    Never raises: an audit-store failure must not turn a successful login into
    a 500, so it is logged and swallowed.
    """
    from .models import AuditEvent

    if request is not None and not actor:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            actor = user.username
            actor_auth_source = actor_auth_source or user.auth_source

    if ip_address is None:
        ip_address = client_ip(request)

    clean = scrub(metadata)

    logger.log(
        level,
        "%s actor=%s source=%s target=%s ip=%s %s",
        action,
        actor or "-",
        actor_auth_source or "-",
        target or "-",
        ip_address or "-",
        " ".join(f"{k}={v}" for k, v in clean.items()) or "-",
    )

    try:
        AuditEvent.objects.create(
            actor=actor[:150],
            actor_auth_source=actor_auth_source[:20],
            action=action[:64],
            target=str(target)[:200],
            ip_address=_valid_ip(ip_address),
            metadata=clean,
        )
    except Exception:  # pragma: no cover - audit must never break a request
        logger.exception("audit_write_failed action=%s", action)


def _valid_ip(value: str | None) -> str | None:
    """GenericIPAddressField rejects junk; a malformed header must not 500."""
    if not value:
        return None
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value
