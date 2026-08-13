"""Deployment checks for the authentication configuration.

These run under ``manage.py check`` and therefore also at container start,
before gunicorn binds. The intent is that a production image refuses to serve
rather than quietly falling back to bootstrap-only sign-in because a Cognito
variable was dropped from the task definition.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register

from .conf import get_bootstrap_config, get_cognito_config

COGNITO_INCOMPLETE = "scrapos.auth.E001"
BOOTSTRAP_HASH_INVALID = "scrapos.auth.E002"
BOOTSTRAP_PLAINTEXT = "scrapos.auth.E003"
BOOTSTRAP_ENABLED_IN_PRODUCTION = "scrapos.auth.W001"
HOSTED_UI_INCOMPLETE = "scrapos.auth.W002"


def _production() -> bool:
    """A real deployment, as opposed to local development or a test run."""
    return not settings.DEBUG and not getattr(settings, "TESTING", False)


@register()
def check_authentication_configuration(app_configs, **kwargs):
    issues = []
    cognito = get_cognito_config()
    boot = get_bootstrap_config()

    if _production() and not cognito.is_configured:
        missing = [
            name
            for name, value in (
                ("COGNITO_REGION", cognito.region),
                ("COGNITO_USER_POOL_ID", cognito.user_pool_id),
                ("COGNITO_CLIENT_ID", cognito.client_id),
            )
            if not value
        ]
        issues.append(
            Error(
                "Cognito is not configured but DEBUG is False.",
                hint=(
                    "Set "
                    + ", ".join(missing)
                    + " on the container. Production must not fall back to "
                    "bootstrap-only sign-in because a variable was omitted."
                ),
                id=COGNITO_INCOMPLETE,
            )
        )

    if _production() and cognito.is_configured and not cognito.hosted_ui_enabled:
        issues.append(
            Warning(
                "Cognito hosted-UI sign-in is unavailable.",
                hint=(
                    "COGNITO_CLIENT_SECRET, COGNITO_DOMAIN and COGNITO_REDIRECT_URI "
                    "are needed for the authorization-code flow. Password sign-in "
                    "still works without them."
                ),
                id=HOSTED_UI_INCOMPLETE,
            )
        )

    if boot.enabled and boot.username and not boot.password_hash:
        issues.append(
            Error(
                "The bootstrap superadmin is enabled but has no password hash.",
                hint="Set SCRAPOS_SUPERADMIN_PASSWORD_HASH, or set SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False.",
                id=BOOTSTRAP_HASH_INVALID,
            )
        )

    if boot.password_hash and "$" not in boot.password_hash:
        issues.append(
            Error(
                "SCRAPOS_SUPERADMIN_PASSWORD_HASH does not look like a Django password hash.",
                hint=(
                    "It must be a hash, not a plaintext password. Generate one with "
                    "`python manage.py hash_bootstrap_password`."
                ),
                id=BOOTSTRAP_PLAINTEXT,
            )
        )

    if _production() and boot.is_configured:
        issues.append(
            Warning(
                "The bootstrap superadmin is enabled in a non-debug environment.",
                hint=(
                    "This account bypasses Cognito by design. Keep it for setup and "
                    "recovery, rotate it regularly, and set "
                    "SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False once Cognito administration "
                    "is stable."
                ),
                id=BOOTSTRAP_ENABLED_IN_PRODUCTION,
            )
        )

    return issues
