"""Centralised access to Scrapos authentication configuration.

Nothing outside this module reads authentication settings directly. That keeps
one answer to "is Cognito usable?" and stops group names from being spelled out
across views, templates and services.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from django.conf import settings


def _setting(name: str, default: str = "") -> str:
    return (getattr(settings, name, default) or "").strip()


@dataclass(frozen=True)
class CognitoConfig:
    """Non-secret Cognito configuration plus the confidential client secret.

    ``client_secret`` never leaves the server: it is used to compute the
    SECRET_HASH for admin auth and to call the token endpoint.
    """

    region: str
    user_pool_id: str
    client_id: str
    client_secret: str
    domain: str
    redirect_uri: str
    logout_redirect_uri: str
    group_admin: str
    group_editor: str
    group_viewer: str

    @property
    def is_configured(self) -> bool:
        """True when a password sign-in against Cognito can be attempted."""
        return bool(self.region and self.user_pool_id and self.client_id)

    @property
    def hosted_ui_enabled(self) -> bool:
        """True when the OAuth2 authorization-code flow can also be offered."""
        return bool(self.is_configured and self.domain and self.redirect_uri and self.client_secret)

    @property
    def issuer(self) -> str:
        return f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/.well-known/jwks.json"

    @property
    def _domain_base(self) -> str:
        domain = self.domain
        if not domain:
            return ""
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        return domain.rstrip("/") + "/"

    @property
    def authorize_url(self) -> str:
        return urljoin(self._domain_base, "oauth2/authorize")

    @property
    def token_url(self) -> str:
        return urljoin(self._domain_base, "oauth2/token")

    @property
    def hosted_logout_url(self) -> str:
        return urljoin(self._domain_base, "logout")

    @property
    def role_groups(self) -> dict[str, str]:
        """Cognito group name -> Scrapos role, most privileged last wins."""
        from .roles import ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_VIEWER

        return {
            self.group_viewer: ROLE_VIEWER,
            self.group_editor: ROLE_EDITOR,
            self.group_admin: ROLE_ADMINISTRATOR,
        }


@dataclass(frozen=True)
class BootstrapConfig:
    """The non-Cognito emergency administrator.

    The password is only ever present as a Django password hash. There is no
    code path that accepts a plaintext bootstrap password from configuration.
    """

    enabled: bool
    username: str
    password_hash: str

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.username and self.password_hash)


def get_cognito_config() -> CognitoConfig:
    return CognitoConfig(
        region=_setting("COGNITO_REGION"),
        user_pool_id=_setting("COGNITO_USER_POOL_ID"),
        client_id=_setting("COGNITO_CLIENT_ID"),
        client_secret=_setting("COGNITO_CLIENT_SECRET"),
        domain=_setting("COGNITO_DOMAIN"),
        redirect_uri=_setting("COGNITO_REDIRECT_URI"),
        logout_redirect_uri=_setting("COGNITO_LOGOUT_REDIRECT_URI"),
        group_admin=_setting("COGNITO_GROUP_ADMIN", "SCRAPOS_ADMIN"),
        group_editor=_setting("COGNITO_GROUP_EDITOR", "SCRAPOS_EDITOR"),
        group_viewer=_setting("COGNITO_GROUP_VIEWER", "SCRAPOS_VIEWER"),
    )


def get_bootstrap_config() -> BootstrapConfig:
    return BootstrapConfig(
        enabled=bool(getattr(settings, "SCRAPOS_BOOTSTRAP_ADMIN_ENABLED", False)),
        username=_setting("SCRAPOS_SUPERADMIN_USERNAME"),
        password_hash=_setting("SCRAPOS_SUPERADMIN_PASSWORD_HASH"),
    )
