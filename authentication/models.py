"""Scrapos-side identity, audit and throttling records.

Cognito owns authentication; Scrapos owns application metadata. The local user
row never holds a password: ``AbstractBaseUser.password`` is left permanently
unusable so there is no local credential to steal or to drift out of sync with
the directory.

``ScraposUser`` is the canonical application identity. It is deliberately *not*
keyed on one Cognito ``sub``: one person can hold several Cognito records
(``Google_…``, ``Facebook_…``, ``SignInWithApple_…``, plus a native account),
and each of those has a ``sub`` of its own. Those provider identities live in
``LinkedIdentity`` rows pointing at the one ``ScraposUser``, mirroring the
member portal's ``LinkedIdentity``/``Person`` split.
"""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from .identity import PROVIDER_CHOICES, PROVIDER_COGNITO
from .roles import (
    AUTH_SOURCE_BOOTSTRAP,
    AUTH_SOURCE_CHOICES,
    AUTH_SOURCE_COGNITO,
    ROLE_CHOICES,
    ROLE_SUPERADMIN,
    ROLE_VIEWER,
    role_at_least,
)


class ScraposUserManager(BaseUserManager):
    def create_user(self, username, **extra):
        if not username:
            raise ValueError("A username is required.")
        user = self.model(username=username, **extra)
        # No local password, ever — see the module docstring.
        user.set_unusable_password()
        user.save(using=self._db)
        return user


class ScraposUser(AbstractBaseUser):
    """Local mirror of an identity that has signed in to Scrapos."""

    username = models.CharField(max_length=150, unique=True)
    cognito_sub = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text=(
            "Cognito subject of the identity this account was first seen through. "
            "Null for the bootstrap account. Not the resolution key — see "
            "LinkedIdentity."
        ),
    )
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    auth_source = models.CharField(
        max_length=20,
        choices=AUTH_SOURCE_CHOICES,
        default=AUTH_SOURCE_COGNITO,
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    objects = ScraposUserManager()

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.username

    @property
    def last_login_at(self):
        """Alias for Django's ``last_login`` under the Scrapos field name."""
        return self.last_login

    @property
    def is_bootstrap(self) -> bool:
        return self.auth_source == AUTH_SOURCE_BOOTSTRAP

    @property
    def is_cognito(self) -> bool:
        return self.auth_source == AUTH_SOURCE_COGNITO

    def has_role(self, minimum: str) -> bool:
        return self.is_active and role_at_least(self.role, minimum)

    @property
    def source_label(self) -> str:
        return "Bootstrap Superadmin" if self.is_bootstrap else "Cognito"

    @property
    def initials(self) -> str:
        source = (self.display_name or self.email or self.username).strip()
        parts = [p for p in source.replace(".", " ").replace("@", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()

    @property
    def is_superadmin(self) -> bool:
        return self.role == ROLE_SUPERADMIN


class LinkedIdentity(models.Model):
    """One authentication identity (native Cognito or federated) of a user.

    A person keeps ONE ``ScraposUser`` however many of these exist. The unique
    key is ``(provider, provider_subject)`` — the provider's own subject, which
    is the only identifier that is stable across Cognito user records. The
    Cognito ``sub`` and ``Username`` are recorded too, because they are what an
    ID token hands us first, but they are per-record and therefore only
    secondary lookup keys.

    Nothing here is ever manufactured: every value is copied from a claim that
    ``authentication.tokens.verify_id_token`` has already validated.
    """

    user = models.ForeignKey(
        "authentication.ScraposUser",
        on_delete=models.CASCADE,
        related_name="linked_identities",
    )
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default=PROVIDER_COGNITO)
    #: Google's ``sub``, Facebook's user id, Apple's ``sub``; for a native
    #: account, the Cognito ``sub``.
    provider_subject = models.CharField(max_length=255)
    #: The Cognito ``Username`` of this identity (``Google_1234…``, or the
    #: email/uuid for a native user). Never the application's identity.
    cognito_username = models.CharField(max_length=255, blank=True, default="", db_index=True)
    #: The AWS-controlled Cognito ``sub`` of the record this identity was seen on.
    cognito_sub = models.CharField(max_length=255, blank=True, default="", db_index=True)
    email = models.EmailField(blank=True, default="")
    normalized_email = models.CharField(max_length=254, blank=True, default="", db_index=True)
    email_verified = models.BooleanField(default=False)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "linked identities"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_subject"],
                name="unique_provider_subject",
            ),
        ]

    def save(self, *args, **kwargs):
        from .emails import normalize_email

        self.normalized_email = normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_provider_display()} identity of {self.user_id}"


class AuditEvent(models.Model):
    """Security-relevant events.

    Only identifiers and outcomes are stored. Passwords, tokens, client secrets
    and AWS credentials must never reach ``metadata`` — see
    ``authentication.audit.record``.
    """

    actor = models.CharField(max_length=150, blank=True)
    actor_auth_source = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    target = models.CharField(max_length=200, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["-created_at", "action"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.actor}"


class LoginAttempt(models.Model):
    """Rows behind the login throttle.

    Kept in the database rather than the cache because gunicorn runs several
    worker processes per container and a locmem cache would not be shared
    between them. Adding Redis purely for this would not be justified.
    """

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    successful = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{'ok' if self.successful else 'fail'} {self.username} {self.created_at:%Y-%m-%d %H:%M}"


__all__ = [
    "ScraposUser",
    "LinkedIdentity",
    "AuditEvent",
    "LoginAttempt",
    "AUTH_SOURCE_BOOTSTRAP",
    "AUTH_SOURCE_COGNITO",
]
