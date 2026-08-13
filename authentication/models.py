"""Scrapos-side identity, audit and throttling records.

Cognito owns authentication; Scrapos owns application metadata. The local user
row is a mirror keyed on the stable Cognito ``sub``, never on email, and it
never holds a password: ``AbstractBaseUser.password`` is left permanently
unusable so there is no local credential to steal or to drift out of sync with
the directory.
"""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

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
        help_text="Stable Cognito subject identifier. Null for the bootstrap account.",
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
    "AuditEvent",
    "LoginAttempt",
    "AUTH_SOURCE_BOOTSTRAP",
    "AUTH_SOURCE_COGNITO",
]
