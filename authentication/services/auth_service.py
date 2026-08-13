"""Provider selection and session establishment.

This is the single decision point for "who is signing in and how":

1. throttle the attempt, per username and per source address;
2. if the username *is* the configured bootstrap account, verify against the
   bootstrap hash and stop — it never reaches Cognito;
3. otherwise authenticate against Cognito and validate the returned ID token;
4. mirror the verified identity into a local ``ScraposUser``;
5. hand back a user for the view to log in.

Keeping this out of the Django authentication-backend chain is deliberate:
there is no ``authenticate()`` call anywhere else that could accidentally let a
second provider answer for a username the first one rejected.
"""

from __future__ import annotations

import logging

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.utils import timezone

from .. import audit, bootstrap, throttling
from ..conf import get_bootstrap_config, get_cognito_config
from ..exceptions import (
    AuthenticationFailed,
    CognitoNotConfigured,
    ScraposAuthError,
    TooManyAttempts,
)
from ..roles import AUTH_SOURCE_COGNITO, role_from_groups
from ..tokens import verify_id_token
from .cognito_service import CognitoService

logger = logging.getLogger("scrapos.auth")

SESSION_AUTH_SOURCE = "scrapos_auth_source"
SESSION_REVALIDATE_AT = "scrapos_revalidate_at"

#: Backend path recorded on the session. ``ScraposSessionBackend`` only loads
#: users; it never verifies a credential.
BACKEND_PATH = "authentication.backends.ScraposSessionBackend"


def authenticate_credentials(request, username: str, password: str, *, service: CognitoService | None = None):
    """Return a ``ScraposUser`` for valid credentials, or raise.

    Raises :class:`TooManyAttempts`, :class:`AuthenticationFailed`, or one of
    the Cognito availability errors. Never returns ``None``.
    """
    username = (username or "").strip()
    ip_address = audit.client_ip(request)

    bootstrap_config = get_bootstrap_config()
    uses_bootstrap = bootstrap.matches_username(username, bootstrap_config)
    source = "bootstrap" if uses_bootstrap else AUTH_SOURCE_COGNITO

    try:
        throttling.check(username, ip_address)
    except TooManyAttempts:
        # Audited, but not counted again: re-recording a failure on every
        # blocked attempt would extend the lockout indefinitely.
        audit.record(
            audit.LOGIN_THROTTLED,
            actor=username,
            actor_auth_source=source,
            ip_address=ip_address,
        )
        raise

    try:
        if uses_bootstrap:
            user = bootstrap.authenticate(username, password, bootstrap_config)
        else:
            user = _authenticate_cognito(username, password, service=service)
    except TooManyAttempts:
        # Cognito reported its own rate limit for this user.
        audit.record(
            audit.LOGIN_THROTTLED,
            actor=username,
            actor_auth_source=source,
            ip_address=ip_address,
            origin="cognito",
        )
        raise
    except AuthenticationFailed as exc:
        throttling.record_failure(username, ip_address)
        audit.record(
            audit.LOGIN_FAILURE,
            actor=username,
            actor_auth_source=source,
            ip_address=ip_address,
            reason=exc.reason,
        )
        raise
    except ScraposAuthError as exc:
        # Configuration or availability problems are not the user's fault and
        # must not count towards their lockout.
        audit.record(
            audit.COGNITO_REQUEST_FAILURE,
            actor=username,
            ip_address=ip_address,
            reason=type(exc).__name__,
        )
        raise

    throttling.record_success(username, ip_address)
    return user


def _authenticate_cognito(username: str, password: str, *, service: CognitoService | None = None):
    config = get_cognito_config()
    if not config.is_configured:
        # Fail loudly and closed. Cognito is never silently skipped just
        # because a variable was omitted.
        raise CognitoNotConfigured()

    service = service or CognitoService(config)
    tokens = service.authenticate(username, password)
    claims = verify_id_token(tokens.id_token, config)
    return sync_user_from_claims(claims, config=config)


def sync_user_from_claims(claims: dict, *, config=None):
    """Create or update the local mirror of a verified Cognito identity.

    Resolution — "which Scrapos account is this?" — is delegated to
    ``identity_service.resolve_user_from_claims``, which matches on the
    person's provider identities rather than on the ``sub`` of a single Cognito
    record. That is what lets someone sign in with Google today and Facebook
    tomorrow and land on the same account.

    This function only mirrors profile data onto whatever account came back.
    Role always comes from the signed ``cognito:groups`` claim, so a sign-in
    through a different provider cannot silently keep a stale role.
    """
    from ..emails import is_apple_private_relay
    from ..identity import email_is_verified, infer_provider
    from .identity_service import resolve_user_from_claims

    config = config or get_cognito_config()
    groups = claims.get("cognito:groups") or []

    user = resolve_user_from_claims(claims)

    if not user.cognito_sub and claims.get("sub"):
        # Backfill the first-seen subject on a row that predates it. Left alone
        # once set: it names one Cognito record, not the person.
        user.cognito_sub = claims["sub"]

    # The username is a label, assigned once at provisioning. Reassigning it to
    # ``cognito:username`` on every sign-in would rename the account to
    # ``Google_1234…`` the first time someone used a social provider, and it is
    # a unique column, so two identities of one person would collide on it.
    claimed_email = claims.get("email", "") or ""
    if claimed_email and email_is_verified(claims, infer_provider(claims)):
        # Only ever overwrite from an address the provider vouched for, and
        # never replace a real address with an Apple relay alias.
        if not (is_apple_private_relay(claimed_email) and user.email and not is_apple_private_relay(user.email)):
            user.email = claimed_email
    elif not user.email:
        user.email = claimed_email

    display_name = (
        claims.get("name")
        or " ".join(filter(None, [claims.get("given_name", ""), claims.get("family_name", "")])).strip()
    )
    user.display_name = display_name or user.display_name
    user.auth_source = AUTH_SOURCE_COGNITO
    user.role = role_from_groups(groups, config)
    user.is_active = True
    if user.has_usable_password():
        user.set_unusable_password()
    user.save()
    return user


def establish_session(request, user) -> None:
    """Log the user in and stamp the session.

    ``django_login`` cycles the session key, which is what prevents session
    fixation: any key an attacker planted before sign-in is discarded.
    """
    django_login(request, user, backend=BACKEND_PATH)
    request.session[SESSION_AUTH_SOURCE] = user.auth_source
    _schedule_revalidation(request)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])


def _schedule_revalidation(request) -> None:
    from django.conf import settings

    seconds = getattr(settings, "SCRAPOS_COGNITO_REVALIDATE_SECONDS", 300)
    request.session[SESSION_REVALIDATE_AT] = timezone.now().timestamp() + seconds


def end_session(request) -> None:
    """Destroy the server-side session."""
    django_logout(request)


def record_login_success(request, user) -> None:
    action = audit.BOOTSTRAP_LOGIN if user.is_bootstrap else audit.LOGIN_SUCCESS
    audit.record(
        action,
        request=request,
        actor=user.username,
        actor_auth_source=user.auth_source,
        role=user.role,
    )
