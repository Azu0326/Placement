"""Test doubles for Cognito.

No test in this suite talks to AWS. Two fakes cover everything:

* :class:`FakeCognitoClient` stands in for the boto3 client, so exception
  translation can be exercised with real ``ClientError`` shapes;
* :func:`signed_id_token` mints a genuinely RS256-signed token against a local
  key pair, so token verification is tested for real rather than stubbed out.
"""

from __future__ import annotations

import json
import time

import jwt
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa

from authentication import tokens

TEST_REGION = "ap-southeast-2"
TEST_POOL_ID = "ap-southeast-2_TESTPOOL"
TEST_CLIENT_ID = "test-client-id"
TEST_CLIENT_SECRET = "test-client-secret"
TEST_KID = "test-key-1"

COGNITO_SETTINGS = {
    "COGNITO_REGION": TEST_REGION,
    "COGNITO_USER_POOL_ID": TEST_POOL_ID,
    "COGNITO_CLIENT_ID": TEST_CLIENT_ID,
    "COGNITO_CLIENT_SECRET": TEST_CLIENT_SECRET,
    "COGNITO_DOMAIN": "auth.example.org",
    "COGNITO_REDIRECT_URI": "https://scrapos.example.org/auth/callback/",
    "COGNITO_LOGOUT_REDIRECT_URI": "https://scrapos.example.org/login/",
    "COGNITO_GROUP_ADMIN": "SCRAPOS_ADMIN",
    "COGNITO_GROUP_EDITOR": "SCRAPOS_EDITOR",
    "COGNITO_GROUP_VIEWER": "SCRAPOS_VIEWER",
}

_private_key = None


def _key():
    global _private_key
    if _private_key is None:
        _private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _private_key


def issuer() -> str:
    return f"https://cognito-idp.{TEST_REGION}.amazonaws.com/{TEST_POOL_ID}"


def jwks_entry(kid: str = TEST_KID) -> dict:
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_key().public_key()))
    public_jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return public_jwk


def install_jwks(kid: str = TEST_KID) -> None:
    """Seed the key cache so verification never performs a network fetch."""
    tokens.reset_jwks_cache()
    tokens._jwks_cache._keys[
        f"{issuer()}/.well-known/jwks.json"
    ] = {kid: jwks_entry(kid)}
    tokens._jwks_cache._fetched_at[f"{issuer()}/.well-known/jwks.json"] = time.monotonic()


def signed_id_token(
    *,
    sub: str = "sub-1234",
    username: str = "jane.doe",
    email: str = "jane.doe@example.org",
    groups: list[str] | None = None,
    audience: str = TEST_CLIENT_ID,
    token_use: str = "id",
    issuer_override: str | None = None,
    expires_in: int = 3600,
    nonce: str | None = None,
    kid: str = TEST_KID,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "cognito:username": username,
        "email": email,
        "name": "Jane Doe",
        "aud": audience,
        "iss": issuer_override or issuer(),
        "token_use": token_use,
        "iat": now,
        "exp": now + expires_in,
    }
    if groups is not None:
        claims["cognito:groups"] = groups
    if nonce is not None:
        claims["nonce"] = nonce

    return jwt.encode(claims, _key(), algorithm=algorithm, headers={"kid": kid})


def client_error(code: str, message: str = "", operation: str = "AdminInitiateAuth") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message or code}},
        operation,
    )


class FakeCognitoClient:
    """Records calls and replays scripted responses or errors."""

    def __init__(self, **responses):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def _resolve(self, operation: str, kwargs: dict):
        self.calls.append((operation, kwargs))
        value = self.responses.get(operation)
        if value is None:
            return {}
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(**kwargs)
        return value

    def __getattr__(self, operation):
        def call(**kwargs):
            return self._resolve(operation, kwargs)

        return call
