"""Email normalisation for identity matching.

Ported from the member portal (``apps/pages/utils/emails.py``) so Scrapos and
member.dncouncil.org decide "is this the same address?" identically. Both
consume the same Cognito user pool, so a difference here would mean the two
applications disagree about who a person is.

Policy, deliberately conservative:

* case-insensitive comparison with surrounding whitespace stripped;
* **no** provider-specific rewriting — no Gmail dot-stripping and no
  plus-address folding, because ``johnsmith@gmail.com`` and
  ``john.smith@gmail.com`` are different identities as far as ownership is
  concerned.

Aggressive deduplication here would be an account-takeover primitive, so it is
not done.
"""

from __future__ import annotations

import hashlib

#: Apple "Hide My Email" addresses. These are per-app relays: two of them are
#: never the same person unless they are byte-identical, which exact matching
#: already gives us.
APPLE_PRIVATE_RELAY_DOMAIN = "privaterelay.appleid.com"


def normalize_email(email: str | None) -> str:
    """Canonical form used for every identity comparison."""
    if not email:
        return ""
    return email.strip().lower()


def is_apple_private_relay(email: str | None) -> bool:
    """True when the address is an Apple Hide My Email relay address."""
    return normalize_email(email).endswith("@" + APPLE_PRIVATE_RELAY_DOMAIN)


def email_hash(email: str | None) -> str:
    """Short, non-reversible fingerprint for structured logs.

    Identity-linking events are logged on every sign-in; logging the raw
    address would put a mailing list in CloudWatch.
    """
    normalized = normalize_email(email)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
