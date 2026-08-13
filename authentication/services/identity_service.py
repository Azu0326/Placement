"""Canonical identity resolution for Scrapos.

Answers one question: *which ``ScraposUser`` is this verified Cognito identity?*

The resolution order is the member portal's
(``apps/pages/services/identity_linking.resolve_member_user``), with the same
security rules:

1. an existing :class:`~authentication.models.LinkedIdentity` — matched first on
   ``(provider, provider_subject)``, then on the Cognito ``sub`` or ``Username``
   seen on a previous sign-in;
2. an existing user with the same **verified** normalised email;
3. otherwise a brand-new user.

Why not just ``sub``: Cognito issues a ``sub`` per *user record*, not per
person. Signing in through Google, Facebook and Apple against an unlinked pool
produces three records and three ``sub`` values for one human being. Keying the
application account on ``sub`` therefore produces three Scrapos accounts, which
is exactly the bug this module exists to remove.

Security rules that must not be relaxed:

* every input comes from claims already validated by
  ``authentication.tokens.verify_id_token`` (signature, issuer, audience,
  expiry, ``token_use``, and ``nonce`` on the hosted-UI path). An email typed
  into a browser never reaches this module;
* email matching happens only for **verified** addresses, and only in
  normalised form (strip + lower, no Gmail tricks);
* an unverified email that collides with an existing account never attaches to
  it — the sign-in gets an isolated account instead;
* two accounts sharing a verified email are never merged automatically. That is
  audited and left for an administrator;
* the bootstrap account is never a resolution target, so no directory identity
  can take over the emergency administrator.

Concurrency: resolution and creation run inside ``transaction.atomic()`` with
``select_for_update`` on the candidate rows and ``IntegrityError`` retries, so
two simultaneous sign-ins cannot create two accounts.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .. import audit
from ..emails import email_hash, is_apple_private_relay, normalize_email
from ..identity import (
    PROVIDER_COGNITO,
    cognito_username,
    email_is_verified,
    infer_provider,
    linkable_identities,
    provider_subject_from,
)
from ..roles import AUTH_SOURCE_BOOTSTRAP, AUTH_SOURCE_COGNITO

logger = logging.getLogger("scrapos.auth")


class ResolvedIdentity:
    """The verified identity of one sign-in, flattened for resolution."""

    __slots__ = (
        "claims",
        "provider",
        "subject",
        "sub",
        "username",
        "email",
        "email_verified",
        "is_private_relay",
        "identities",
    )

    def __init__(self, claims: dict):
        self.claims = claims
        self.sub = (claims.get("sub") or "").strip()
        self.username = cognito_username(claims)
        self.provider = infer_provider(claims)
        self.subject = provider_subject_from(claims, self.provider)
        self.email = normalize_email(claims.get("email"))
        self.email_verified = email_is_verified(claims, self.provider)
        self.is_private_relay = is_apple_private_relay(self.email)
        self.identities = linkable_identities(claims)

    @property
    def lookup_keys(self) -> list[str]:
        """Per-record identifiers usable as secondary lookup keys."""
        keys = [self.sub, self.username, self.subject]
        keys.extend(subject for _provider, subject in self.identities)
        return [key for key in dict.fromkeys(keys) if key]

    @property
    def display_name(self) -> str:
        claims = self.claims
        given = claims.get("given_name", "") or ""
        family = claims.get("family_name", "") or ""
        return claims.get("name") or " ".join(filter(None, [given, family])).strip()


def _log(event: str, **fields) -> None:
    """One structured, CloudWatch-searchable line. Never an address, never a token."""
    parts = [f"event={event}"]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    logger.info(" ".join(parts))


def _linked_user(identity: ResolvedIdentity):
    """Step 1 — an identity we have already seen."""
    from ..models import LinkedIdentity

    for provider, subject in identity.identities:
        row = (
            LinkedIdentity.objects.select_related("user")
            .filter(provider=provider, provider_subject=subject)
            .first()
        )
        if row is not None:
            return row.user, "matched_provider_subject"

    keys = identity.lookup_keys
    if keys:
        row = (
            LinkedIdentity.objects.select_related("user")
            .filter(cognito_sub__in=keys)
            .order_by("pk")
            .first()
        )
        if row is not None:
            return row.user, "matched_cognito_sub"

        row = (
            LinkedIdentity.objects.select_related("user")
            .filter(cognito_username__in=keys)
            .order_by("pk")
            .first()
        )
        if row is not None:
            return row.user, "matched_cognito_username"

    return None, ""


def _legacy_user(identity: ResolvedIdentity):
    """Rows written before ``LinkedIdentity`` existed and never backfilled."""
    from ..models import ScraposUser

    if not identity.sub:
        return None
    return (
        ScraposUser.objects.filter(cognito_sub=identity.sub)
        .exclude(auth_source=AUTH_SOURCE_BOOTSTRAP)
        .first()
    )


def _pick_canonical(candidates: list):
    """Deterministic choice when a verified email matches several accounts.

    Prefer the account that holds a native (email/password) identity, then the
    oldest row. Same rule as the member portal's ``_pick_canonical_person``.
    """

    def sort_key(user):
        has_native = user.linked_identities.filter(provider=PROVIDER_COGNITO).exists()
        return (0 if has_native else 1, user.created_at, user.pk)

    return sorted(candidates, key=sort_key)[0]


def _users_by_verified_email(identity: ResolvedIdentity) -> list:
    """Step 2 candidates. Only ever called for a verified address."""
    from ..models import ScraposUser

    if not identity.email:
        return []
    return list(
        ScraposUser.objects.select_for_update()
        .filter(email__iexact=identity.email)
        .exclude(auth_source=AUTH_SOURCE_BOOTSTRAP)
        .order_by("created_at", "pk")
    )


def _unique_username(preferred: str) -> str:
    """A free username, suffixing on collision.

    Only used when creating an account. The username is a label from that point
    on — it is never the resolution key, so a later sign-in through a different
    provider does not rename or reuse it.
    """
    from ..models import ScraposUser

    base = (preferred or "user").strip()[:140] or "user"
    candidate = base
    counter = 1
    while ScraposUser.objects.filter(username=candidate).exists():
        suffix = f"_{counter}"
        candidate = f"{base[:140 - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def _preferred_username(identity: ResolvedIdentity) -> str:
    """A human-readable username that is not tied to one provider.

    ``Google_110248…`` is a Cognito record name, not a person, so the email
    local part is preferred — the same choice the member portal makes in
    ``_create_local_user``.
    """
    if identity.email and not identity.is_private_relay:
        local_part = identity.email.split("@")[0]
        if local_part:
            return local_part
    if identity.username and identity.provider == PROVIDER_COGNITO:
        return identity.username
    return f"{identity.provider}_{identity.subject}"[:140] or identity.sub


def _create_user(identity: ResolvedIdentity):
    """Step 3 — provision, retrying once if a concurrent sign-in won the race."""
    from ..models import ScraposUser

    preferred = _preferred_username(identity)
    for _attempt in range(3):
        try:
            with transaction.atomic():
                user = ScraposUser(
                    username=_unique_username(preferred),
                    cognito_sub=identity.sub or None,
                    email=identity.claims.get("email", "") or "",
                    display_name=identity.display_name,
                    auth_source=AUTH_SOURCE_COGNITO,
                )
                user.set_unusable_password()
                user.save()
                return user
        except IntegrityError:
            # Either the username or the cognito_sub was taken between the
            # check and the insert. If it was the sub, the other request has
            # already provisioned this very person.
            existing = _legacy_user(identity)
            if existing is not None:
                return existing
    raise IntegrityError("Could not provision a Scrapos user for this identity.")


def _upsert_linked_identities(user, identity: ResolvedIdentity) -> list:
    """Record every provider identity this token proves, against ``user``.

    Recording *all* of them is what makes Cognito-side linking work: when a
    record linked with ``AdminLinkProviderForUser`` signs in, its ID token
    carries every linked provider, so the next sign-in through any of them is an
    exact ``(provider, provider_subject)`` match.
    """
    from ..models import LinkedIdentity

    now = timezone.now()
    created_rows = []
    for provider, subject in identity.identities:
        if not subject:
            continue
        try:
            with transaction.atomic():
                row, created = LinkedIdentity.objects.get_or_create(
                    provider=provider,
                    provider_subject=subject,
                    defaults={
                        "user": user,
                        "cognito_username": identity.username,
                        "cognito_sub": identity.sub,
                        "email": identity.claims.get("email", "") or "",
                        "email_verified": identity.email_verified,
                        "last_login_at": now,
                    },
                )
        except IntegrityError:  # pragma: no cover - concurrent insert
            row = LinkedIdentity.objects.get(provider=provider, provider_subject=subject)
            created = False

        if created:
            created_rows.append(row)
            continue

        updates = ["last_login_at"]
        row.last_login_at = now
        if identity.sub and row.cognito_sub != identity.sub:
            row.cognito_sub = identity.sub
            updates.append("cognito_sub")
        if identity.username and row.cognito_username != identity.username:
            row.cognito_username = identity.username
            updates.append("cognito_username")
        if identity.email and row.normalized_email != identity.email:
            row.email = identity.claims.get("email", "") or ""
            updates.extend(["email", "normalized_email"])
        if identity.email_verified and not row.email_verified:
            row.email_verified = True
            updates.append("email_verified")
        row.save(update_fields=list(dict.fromkeys(updates)))

    return created_rows


def resolve_user_from_claims(claims: dict):
    """Return the ``ScraposUser`` that owns this verified Cognito identity.

    Creates one only when no existing account can be proven to be the same
    person.
    """
    from ..models import ScraposUser

    identity = ResolvedIdentity(claims)
    fingerprint = email_hash(identity.email)

    _log(
        "identity_resolve_attempt",
        provider=identity.provider,
        email_hash=fingerprint,
        email_verified=identity.email_verified,
        apple_private_relay=identity.is_private_relay,
        linked_identities=len(identity.identities),
    )

    with transaction.atomic():
        # ---- 1. An identity we have already recorded --------------------
        user, how = _linked_user(identity)
        if user is None:
            user = _legacy_user(identity)
            how = "matched_legacy_sub" if user is not None else ""

        if user is not None:
            _upsert_linked_identities(user, identity)
            _log(
                "identity_resolve_success",
                provider=identity.provider,
                email_hash=fingerprint,
                existing_user="true",
                result=how,
                user_id=user.pk,
            )
            return user

        # ---- 2. Verified email against an existing account ---------------
        candidates: list = []
        if identity.email and identity.email_verified:
            candidates = _users_by_verified_email(identity)
        elif identity.email:
            _log(
                "identity_resolve_skipped",
                provider=identity.provider,
                email_hash=fingerprint,
                reason="email_unverified",
            )

        if len(candidates) > 1:
            # Never auto-merge. Sign the person in to the deterministic choice
            # and flag it, but do not persist a link against a guess.
            user = _pick_canonical(candidates)
            _log(
                "identity_duplicate_detected",
                provider=identity.provider,
                email_hash=fingerprint,
                candidates=len(candidates),
                user_id=user.pk,
            )
            audit.record(
                audit.IDENTITY_DUPLICATE_DETECTED,
                actor=user.username,
                actor_auth_source=AUTH_SOURCE_COGNITO,
                target=user.username,
                provider=identity.provider,
                email_fingerprint=fingerprint,
                candidates=len(candidates),
            )
            return user

        if candidates:
            user = candidates[0]
            created_rows = _upsert_linked_identities(user, identity)
            if created_rows:
                audit.record(
                    audit.IDENTITY_LINKED,
                    actor=user.username,
                    actor_auth_source=AUTH_SOURCE_COGNITO,
                    target=user.username,
                    provider=identity.provider,
                    email_fingerprint=fingerprint,
                    basis="verified_email",
                )
            _log(
                "identity_resolve_success",
                provider=identity.provider,
                email_hash=fingerprint,
                existing_user="true",
                result="linked_by_verified_email" if created_rows else "refreshed",
                user_id=user.pk,
            )
            return user

        # ---- 3. A genuinely new person -----------------------------------
        if identity.email and not identity.email_verified:
            collides = ScraposUser.objects.filter(email__iexact=identity.email).exists()
            if collides:
                # An unverified address that matches an existing account gets an
                # isolated account, never that one.
                _log(
                    "identity_resolve_skipped",
                    provider=identity.provider,
                    email_hash=fingerprint,
                    reason="unverified_email_collision_isolated",
                )

        user = _create_user(identity)
        _upsert_linked_identities(user, identity)
        _log(
            "identity_resolve_success",
            provider=identity.provider,
            email_hash=fingerprint,
            existing_user="false",
            result="created",
            user_id=user.pk,
        )
        return user


def local_user_for_cognito_username(username: str):
    """The Scrapos account behind a Cognito ``Username``, for the admin directory.

    A federated record is called ``Google_1234…`` in Cognito but is not called
    that in Scrapos, so the directory has to go through ``LinkedIdentity``
    rather than assuming the two names match.
    """
    from ..models import LinkedIdentity, ScraposUser

    if not username:
        return None
    user = ScraposUser.objects.filter(username=username).first()
    if user is not None:
        return user
    row = (
        LinkedIdentity.objects.select_related("user")
        .filter(cognito_username=username)
        .order_by("pk")
        .first()
    )
    return row.user if row is not None else None


def local_users_by_cognito_username() -> dict:
    """Bulk form of :func:`local_user_for_cognito_username`."""
    from ..models import LinkedIdentity, ScraposUser

    mapping = {user.username: user for user in ScraposUser.objects.all()}
    for row in LinkedIdentity.objects.select_related("user").exclude(cognito_username=""):
        mapping.setdefault(row.cognito_username, row.user)
    return mapping
