"""Hosted-UI sign-in (OAuth2 authorization code flow with PKCE).

Offered alongside the Scrapos password form because the rest of the DNC estate
already brokers sign-in through ``auth.dncouncil.org``. Only the authorization
code flow is implemented — the implicit flow is not supported anywhere here.

Per-request ``state``, ``nonce`` and PKCE verifier live in the server-side
session, never in a cookie readable by JavaScript, and each is consumed exactly
once so a replayed callback fails.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

from .conf import CognitoConfig
from .exceptions import AuthenticationFailed

SESSION_STATE = "scrapos_oidc_state"
SESSION_NONCE = "scrapos_oidc_nonce"
SESSION_VERIFIER = "scrapos_oidc_verifier"
SESSION_NEXT = "scrapos_oidc_next"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def begin(request, config: CognitoConfig, *, next_url: str = "") -> str:
    """Store one-time parameters in the session and return the authorize URL."""
    state = _b64url(secrets.token_bytes(32))
    nonce = _b64url(secrets.token_bytes(32))
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

    request.session[SESSION_STATE] = state
    request.session[SESSION_NONCE] = nonce
    request.session[SESSION_VERIFIER] = verifier
    request.session[SESSION_NEXT] = next_url or ""

    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{config.authorize_url}?{query}"


def consume(request, state: str) -> tuple[str, str, str]:
    """Validate the returned ``state`` and hand back the stored parameters.

    Returns ``(nonce, code_verifier, next_url)``. Everything is popped from the
    session first, so a second callback with the same code cannot succeed even
    if the first one failed.
    """
    expected = request.session.pop(SESSION_STATE, None)
    nonce = request.session.pop(SESSION_NONCE, "")
    verifier = request.session.pop(SESSION_VERIFIER, "")
    next_url = request.session.pop(SESSION_NEXT, "")

    if not expected or not state or not secrets.compare_digest(str(state), str(expected)):
        raise AuthenticationFailed(
            "Sign-in could not be completed. Please try again.",
            reason="oidc_state_mismatch",
        )

    return nonce, verifier, next_url


def logout_url(config: CognitoConfig, redirect_to: str) -> str:
    """Hosted-UI logout, so the Cognito session ends too and not just ours."""
    query = urlencode({"client_id": config.client_id, "logout_uri": redirect_to})
    return f"{config.hosted_logout_url}?{query}"
