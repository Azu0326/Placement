"""The non-Cognito bootstrap superadmin.

This account exists so Scrapos can be set up, and recovered, when Cognito is
unreachable or misconfigured. It is deliberately narrow:

* exactly one username, taken from configuration, may use this path;
* only a Django password *hash* is ever configured — there is no code path that
  accepts a plaintext bootstrap password from the environment;
* the account is never created in, looked up in, or written to Cognito;
* it is subject to the same login throttle as every Cognito user.

Rotation is a secret update plus a redeploy — see docs/authentication.md. It
never requires a code change or a commit.
"""

from __future__ import annotations

import hmac
import logging

from django.contrib.auth.hashers import check_password, is_password_usable

from .conf import BootstrapConfig, get_bootstrap_config
from .exceptions import AuthenticationFailed
from .roles import AUTH_SOURCE_BOOTSTRAP, ROLE_SUPERADMIN

logger = logging.getLogger("scrapos.auth")


def matches_username(username: str, config: BootstrapConfig | None = None) -> bool:
    """Whether this username is *the* bootstrap account.

    Compared case-insensitively and in constant time so the comparison itself
    cannot be used to recover the configured username character by character.
    """
    config = config or get_bootstrap_config()
    if not config.is_configured:
        return False
    return hmac.compare_digest(
        (username or "").strip().casefold(),
        config.username.strip().casefold(),
    )


def verify_password(password: str, config: BootstrapConfig | None = None) -> bool:
    config = config or get_bootstrap_config()
    if not config.is_configured:
        return False
    if not is_password_usable(config.password_hash):
        # A malformed or unusable hash must fail closed rather than match.
        logger.error("bootstrap_admin_hash_invalid")
        return False
    try:
        return check_password(password or "", config.password_hash)
    except ValueError:
        logger.error("bootstrap_admin_hash_unreadable")
        return False


def authenticate(username: str, password: str, config: BootstrapConfig | None = None):
    """Verify the bootstrap credential and return its local user row.

    Raises :class:`AuthenticationFailed` on a bad password. The caller must not
    fall through to Cognito afterwards: the bootstrap username is reserved, and
    letting it reach the directory is exactly the confusion this account must
    not create.
    """
    from .models import ScraposUser

    config = config or get_bootstrap_config()
    if not matches_username(username, config) or not verify_password(password, config):
        raise AuthenticationFailed(reason="bootstrap_invalid_credentials")

    user, _ = ScraposUser.objects.get_or_create(
        username=config.username,
        defaults={
            "auth_source": AUTH_SOURCE_BOOTSTRAP,
            "role": ROLE_SUPERADMIN,
            "display_name": "Bootstrap Superadmin",
            "is_active": True,
        },
    )

    # Repair the row if anything drifted — the bootstrap account must never be
    # left inactive, demoted, or attached to a Cognito subject.
    changed = False
    for attribute, expected in (
        ("auth_source", AUTH_SOURCE_BOOTSTRAP),
        ("role", ROLE_SUPERADMIN),
        ("is_active", True),
        ("cognito_sub", None),
    ):
        if getattr(user, attribute) != expected:
            setattr(user, attribute, expected)
            changed = True
    if user.has_usable_password():
        user.set_unusable_password()
        changed = True
    if changed:
        user.save()

    return user
