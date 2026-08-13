"""Reading a person's provider identities out of verified Cognito claims.

Scrapos and member.dncouncil.org share one Cognito user pool. The member portal
resolves a person from the Cognito *username prefix* (``Google_…``,
``Facebook_…``, ``SignInWithApple_…``); this module keeps that behaviour
verbatim as a fallback, but prefers the ``identities`` claim when Cognito sends
one, because that is where Cognito publishes the *whole* set of providers
attached to a user record.

That distinction is the point of the whole exercise:

* an unlinked federated sign-in produces its own Cognito user, so ``sub`` alone
  cannot tell you that ``Google_123`` and ``Facebook_987`` are one person;
* a sign-in against a user that was linked with ``AdminLinkProviderForUser``
  carries *every* linked provider in ``identities``, so recording all of them
  makes the next sign-in through any of those providers an exact match.

Everything here reads claims that have already been through
``authentication.tokens.verify_id_token``. Nothing in this module accepts a
value supplied by the browser.
"""

from __future__ import annotations

import json

PROVIDER_COGNITO = "cognito"
PROVIDER_GOOGLE = "google"
PROVIDER_FACEBOOK = "facebook"
PROVIDER_APPLE = "apple"
PROVIDER_OTHER = "other"

PROVIDER_CHOICES = [
    (PROVIDER_COGNITO, "Email/password"),
    (PROVIDER_GOOGLE, "Google"),
    (PROVIDER_FACEBOOK, "Facebook"),
    (PROVIDER_APPLE, "Apple"),
    (PROVIDER_OTHER, "Other"),
]

#: URL slug -> the identity-provider name configured in the Cognito user pool
#: (Federation > Identity providers). These names are what the hosted UI's
#: ``identity_provider`` parameter expects, and they must stay identical to the
#: member portal's ``SOCIAL_PROVIDERS`` because it is the same pool.
SOCIAL_PROVIDERS = {
    PROVIDER_GOOGLE: "Google",
    PROVIDER_APPLE: "SignInWithApple",
    PROVIDER_FACEBOOK: "Facebook",
}

#: Cognito's ``providerName`` -> our slug, for reading the ``identities`` claim.
_COGNITO_PROVIDER_NAMES = {name.lower(): slug for slug, name in SOCIAL_PROVIDERS.items()}

#: Cognito username prefixes for federated identities. Same table as the member
#: portal's ``PROVIDER_USERNAME_PREFIXES``.
PROVIDER_USERNAME_PREFIXES = (
    ("google_", PROVIDER_GOOGLE),
    ("facebook_", PROVIDER_FACEBOOK),
    ("signinwithapple_", PROVIDER_APPLE),
)

#: Providers whose email claim proves ownership even when Cognito maps no
#: ``email_verified`` attribute for them.
#:
#: Facebook only ever releases addresses it has verified, and the pool's
#: attribute mapping carries no ``email_verified`` for it. A native Cognito
#: account cannot authenticate while UNCONFIRMED, so a successful sign-in is
#: itself the confirmation. Google and Apple *do* map ``email_verified``, so for
#: them an absent claim means "not verified" and must not link anything.
PROVIDERS_TRUSTED_WITHOUT_CLAIM = {PROVIDER_FACEBOOK, PROVIDER_COGNITO}


def cognito_username(claims: dict) -> str:
    return (claims.get("cognito:username") or claims.get("username") or "").strip()


def _provider_from_username(username: str) -> str | None:
    lowered = username.lower()
    for prefix, provider in PROVIDER_USERNAME_PREFIXES:
        if lowered.startswith(prefix):
            return provider
    return None


def _coerce_identities(raw) -> list[dict]:
    """Cognito sends ``identities`` as a list in tokens, a JSON string elsewhere."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if isinstance(raw, dict):
        raw = [raw]
    return [item for item in raw if isinstance(item, dict)]


def _is_primary(entry: dict) -> bool:
    # Cognito writes this as a real boolean in the token and as the string
    # "true" in the user attribute.
    return str(entry.get("primary", "")).strip().lower() == "true"


def federated_identities(claims: dict) -> list[tuple[str, str]]:
    """``[(provider_slug, provider_subject)]`` from the ``identities`` claim.

    Order is preserved except that Cognito's ``primary`` entry is moved to the
    front, so callers that only want "which provider is this sign-in" can read
    the first element. Entries without a ``userId`` are dropped — a link with no
    subject is not something we can key on.
    """
    found: list[tuple[str, str]] = []
    for entry in _coerce_identities(claims.get("identities")):
        subject = str(entry.get("userId") or "").strip()
        if not subject:
            continue
        name = str(entry.get("providerName") or entry.get("providerType") or "").strip()
        provider = _COGNITO_PROVIDER_NAMES.get(name.lower(), PROVIDER_OTHER)
        pair = (provider, subject)
        if pair in found:
            continue
        if _is_primary(entry):
            found.insert(0, pair)
        else:
            found.append(pair)
    return found


def infer_provider(claims: dict) -> str:
    """Which provider *this* sign-in came through.

    ``identities`` first, then the Cognito username prefix (the member portal's
    only signal), then native Cognito.
    """
    identities = federated_identities(claims)
    if identities:
        return identities[0][0]

    from_username = _provider_from_username(cognito_username(claims))
    if from_username:
        return from_username

    return PROVIDER_COGNITO


def provider_subject_from(claims: dict, provider: str) -> str:
    """The stable per-provider subject used as the linking key.

    For a federated identity this is the provider's own subject (Google's ``sub``,
    Facebook's user id, Apple's ``sub``) — the part after the underscore in
    ``Google_1234``. For a native account it is the Cognito ``sub``.
    """
    if provider != PROVIDER_COGNITO:
        for candidate_provider, subject in federated_identities(claims):
            if candidate_provider == provider:
                return subject
        username = cognito_username(claims)
        if "_" in username:
            return username.split("_", 1)[1] or username
        return username or (claims.get("sub") or "")
    return (claims.get("sub") or "").strip() or cognito_username(claims)


def email_is_verified(claims: dict, provider: str) -> bool:
    """True when Cognito/the provider confirms ownership of the email.

    An explicit ``email_verified`` claim decides it in both directions; only
    when the claim is absent do we fall back to
    :data:`PROVIDERS_TRUSTED_WITHOUT_CLAIM`. Identical to the member portal's
    ``email_is_verified``.
    """
    raw = claims.get("email_verified")
    if raw is not None:
        return str(raw).strip().lower() == "true"
    return provider in PROVIDERS_TRUSTED_WITHOUT_CLAIM


def linkable_identities(claims: dict) -> list[tuple[str, str]]:
    """Every ``(provider, subject)`` pair this token proves the user owns.

    Includes the native Cognito identity, so a user that started as
    email/password and later had Google linked to it keeps one row per identity
    and matches on the next sign-in whichever way it arrives.
    """
    pairs = federated_identities(claims)

    sub = (claims.get("sub") or "").strip()
    username = cognito_username(claims)
    if sub and not _provider_from_username(username):
        # No provider prefix on the username: this record is a native
        # (email/password) Cognito account, possibly with federated identities
        # linked into it.
        native = (PROVIDER_COGNITO, sub)
        if native not in pairs:
            pairs.append(native)

    if not pairs:
        provider = infer_provider(claims)
        subject = provider_subject_from(claims, provider)
        if subject:
            pairs.append((provider, subject))

    return pairs
