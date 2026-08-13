"""Cognito ID token verification.

Both sign-in paths — the server-side password flow and the hosted-UI
authorization-code flow — end here. A token is only trusted after its
signature, issuer, audience, expiry and ``token_use`` have all been checked
against the pool's published JWKS. Claims are never read from an unverified
token, including for logging.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

import jwt
from jwt.algorithms import RSAAlgorithm

from .conf import CognitoConfig
from .exceptions import CognitoUnavailable, InvalidToken

logger = logging.getLogger("scrapos.auth")

#: Seconds a fetched key set is reused before a background-free refresh.
JWKS_TTL_SECONDS = 3600
JWKS_FETCH_TIMEOUT = 5

#: Cognito's own clock skew allowance for exp/iat checks.
LEEWAY_SECONDS = 30


class _JwksCache:
    """Key set per issuer, refreshed on TTL expiry or on an unknown ``kid``.

    Refreshing on an unknown key id is what makes signing-key rotation a
    non-event: the first token signed by a new key triggers exactly one extra
    fetch, and a token with a bogus kid costs at most one fetch per
    ``_MIN_REFRESH_INTERVAL``.
    """

    _MIN_REFRESH_INTERVAL = 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, dict] = {}
        self._fetched_at: dict[str, float] = {}

    def clear(self) -> None:
        with self._lock:
            self._keys.clear()
            self._fetched_at.clear()

    def get_key(self, jwks_url: str, kid: str) -> dict:
        with self._lock:
            cached = self._keys.get(jwks_url)
            age = time.monotonic() - self._fetched_at.get(jwks_url, 0.0)

            if cached is None or age > JWKS_TTL_SECONDS:
                cached = self._fetch(jwks_url)
            elif kid not in cached and age > self._MIN_REFRESH_INTERVAL:
                cached = self._fetch(jwks_url)

            key = cached.get(kid)
            if key is None:
                raise InvalidToken("Token was signed with an unknown key.")
            return key

    def _fetch(self, jwks_url: str) -> dict[str, dict]:
        try:
            request = urllib.request.Request(jwks_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=JWKS_FETCH_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("cognito_request_failure operation=jwks error=%s", type(exc).__name__)
            raise CognitoUnavailable() from exc

        keys = {key["kid"]: key for key in payload.get("keys", []) if key.get("kid")}
        if not keys:
            raise CognitoUnavailable()

        self._keys[jwks_url] = keys
        self._fetched_at[jwks_url] = time.monotonic()
        return keys


_jwks_cache = _JwksCache()


def reset_jwks_cache() -> None:
    """Test and operational hook — forces the next verification to refetch."""
    _jwks_cache.clear()


def verify_id_token(token: str, config: CognitoConfig, *, nonce: str | None = None) -> dict:
    """Return the verified claims of a Cognito ID token.

    Raises :class:`InvalidToken` for anything that fails validation and
    :class:`CognitoUnavailable` if the key set cannot be fetched.
    """
    if not token:
        raise InvalidToken("No token supplied.")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise InvalidToken("Token header could not be read.") from exc

    kid = header.get("kid")
    if not kid:
        raise InvalidToken("Token has no key id.")
    if header.get("alg") != "RS256":
        # Pinning the algorithm blocks "alg: none" and HMAC-confusion attacks.
        raise InvalidToken("Unexpected token signing algorithm.")

    jwk = _jwks_cache.get_key(config.jwks_url, kid)
    public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))

    try:
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=config.client_id,
            issuer=config.issuer,
            leeway=LEEWAY_SECONDS,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub", "token_use"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise InvalidToken("Token failed validation.") from exc

    # An access token carries the same signature and issuer but a different
    # audience contract; only an ID token may establish a session.
    if claims.get("token_use") != "id":
        raise InvalidToken("Token is not an ID token.")

    if not claims.get("sub"):
        raise InvalidToken("Token has no subject.")

    if nonce is not None and claims.get("nonce") != nonce:
        raise InvalidToken("Token nonce does not match the authentication request.")

    return claims
