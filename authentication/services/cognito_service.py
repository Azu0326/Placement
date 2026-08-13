"""The only place in Scrapos that talks to AWS Cognito.

Views, templates and the dashboard call this service; none of them import
boto3. Every botocore error is translated into an ``authentication.exceptions``
type here, so an AWS error string can never reach a rendered page.

Credentials come from the ECS task role. Nothing in this module reads an access
key, and no AWS identity or token is ever passed to the browser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..conf import CognitoConfig, get_cognito_config
from ..exceptions import (
    AuthenticationFailed,
    ChallengeRequired,
    CognitoNotConfigured,
    CognitoOperationFailed,
    CognitoPermissionDenied,
    CognitoUnavailable,
    PasswordResetRequired,
    TooManyAttempts,
    UserDisabled,
    UserNotConfirmed,
)

logger = logging.getLogger("scrapos.auth")


@dataclass(frozen=True)
class AuthTokens:
    id_token: str
    access_token: str = ""
    expires_in: int = 0


@dataclass
class CognitoUser:
    """A directory user, flattened for the dashboard."""

    username: str
    sub: str = ""
    email: str = ""
    name: str = ""
    enabled: bool = True
    status: str = ""
    created_at: Any = None
    last_modified_at: Any = None
    groups: list[str] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name or self.email or self.username


def _attributes_to_dict(attributes: Iterable[dict]) -> dict[str, str]:
    return {item["Name"]: item.get("Value", "") for item in attributes or ()}


class CognitoService:
    """Least-privilege wrapper over the Cognito Identity Provider API."""

    def __init__(self, config: CognitoConfig | None = None, client=None):
        self._config = config or get_cognito_config()
        self._client = client

    @property
    def config(self) -> CognitoConfig:
        return self._config

    @property
    def is_configured(self) -> bool:
        return self._config.is_configured

    # -- plumbing ---------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            if not self._config.is_configured:
                raise CognitoNotConfigured()
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "cognito-idp",
                region_name=self._config.region,
                config=Config(
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=5,
                    read_timeout=10,
                ),
            )
        return self._client

    def _secret_hash(self, username: str) -> str | None:
        """Cognito's HMAC proof that the caller holds the client secret."""
        if not self._config.client_secret:
            return None
        digest = hmac.new(
            self._config.client_secret.encode("utf-8"),
            (username + self._config.client_id).encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode()

    def _call(self, operation: str, **kwargs):
        """Invoke a Cognito operation, translating every failure mode."""
        from botocore.exceptions import BotoCoreError, ClientError

        method = getattr(self.client, operation)
        try:
            return method(**kwargs)
        except ClientError as exc:
            raise self._translate(operation, exc) from exc
        except BotoCoreError as exc:
            logger.warning("cognito_request_failure operation=%s error=%s", operation, type(exc).__name__)
            raise CognitoUnavailable() from exc

    def _translate(self, operation: str, exc) -> Exception:
        error = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
        code = error.get("Code", "")
        message = error.get("Message", "") or ""

        # Logged at WARNING with the AWS code but never the request payload,
        # so operators can diagnose without credentials entering the log.
        logger.warning("cognito_request_failure operation=%s code=%s", operation, code or "unknown")

        if code in {"NotAuthorizedException"}:
            lowered = message.lower()
            if "disabled" in lowered:
                return UserDisabled()
            if "attempts exceeded" in lowered or "rate exceeded" in lowered:
                return TooManyAttempts()
            return AuthenticationFailed()
        if code in {"UserNotFoundException"}:
            # Uniform with a wrong password so the response cannot enumerate users.
            return AuthenticationFailed()
        if code == "PasswordResetRequiredException":
            return PasswordResetRequired()
        if code == "UserNotConfirmedException":
            return UserNotConfirmed()
        if code in {"TooManyRequestsException", "LimitExceededException", "TooManyFailedAttemptsException"}:
            return TooManyAttempts()
        if code in {"AccessDeniedException", "UnauthorizedException"}:
            return CognitoPermissionDenied()
        if code in {"InternalErrorException", "ServiceUnavailableException"}:
            return CognitoUnavailable()
        if code in {"ResourceNotFoundException"}:
            return CognitoNotConfigured()
        if code in {
            "UsernameExistsException",
            "InvalidParameterException",
            "InvalidPasswordException",
            "AliasExistsException",
            "GroupExistsException",
        }:
            return CognitoOperationFailed(_safe_operation_message(code))
        return CognitoUnavailable()

    # -- authentication ---------------------------------------------------

    def authenticate(self, username: str, password: str) -> AuthTokens:
        """Verify a username/password against Cognito, server-side.

        Uses ADMIN_USER_PASSWORD_AUTH: it requires both the confidential client
        secret and signed IAM credentials, so unlike USER_PASSWORD_AUTH it is
        not something a browser could ever call directly.
        """
        if not self._config.is_configured:
            raise CognitoNotConfigured()

        params = {"USERNAME": username, "PASSWORD": password}
        secret_hash = self._secret_hash(username)
        if secret_hash:
            params["SECRET_HASH"] = secret_hash

        response = self._call(
            "admin_initiate_auth",
            UserPoolId=self._config.user_pool_id,
            ClientId=self._config.client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters=params,
        )

        challenge = response.get("ChallengeName")
        if challenge:
            # NEW_PASSWORD_REQUIRED, MFA setup and friends. Scrapos does not
            # drive these; the user finishes setup in the hosted UI instead.
            raise ChallengeRequired(challenge)

        result = response.get("AuthenticationResult") or {}
        id_token = result.get("IdToken")
        if not id_token:
            raise CognitoUnavailable()

        return AuthTokens(
            id_token=id_token,
            access_token=result.get("AccessToken", ""),
            expires_in=int(result.get("ExpiresIn") or 0),
        )

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str = "") -> AuthTokens:
        """Swap a hosted-UI authorization code for tokens at the token endpoint.

        The client secret goes in the Basic auth header, never the body, and the
        PKCE verifier proves this is the same session that started the flow.
        """
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        if not self._config.hosted_ui_enabled:
            raise CognitoNotConfigured()

        form = {
            "grant_type": "authorization_code",
            "client_id": self._config.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            form["code_verifier"] = code_verifier
        body = urllib.parse.urlencode(form).encode()

        basic = base64.b64encode(
            f"{self._config.client_id}:{self._config.client_secret}".encode()
        ).decode()

        request = urllib.request.Request(
            self._config.token_url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The body can echo the request; log only the status.
            logger.warning("cognito_request_failure operation=token_exchange status=%s", exc.code)
            raise AuthenticationFailed() from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("cognito_request_failure operation=token_exchange error=%s", type(exc).__name__)
            raise CognitoUnavailable() from exc

        id_token = payload.get("id_token")
        if not id_token:
            raise AuthenticationFailed()

        return AuthTokens(
            id_token=id_token,
            access_token=payload.get("access_token", ""),
            expires_in=int(payload.get("expires_in") or 0),
        )

    # -- directory reads --------------------------------------------------

    def get_user(self, username: str) -> CognitoUser:
        response = self._call(
            "admin_get_user",
            UserPoolId=self._config.user_pool_id,
            Username=username,
        )
        attributes = _attributes_to_dict(response.get("UserAttributes", []))
        return CognitoUser(
            username=response.get("Username", username),
            sub=attributes.get("sub", ""),
            email=attributes.get("email", ""),
            name=attributes.get("name") or attributes.get("given_name", ""),
            enabled=bool(response.get("Enabled", True)),
            status=response.get("UserStatus", ""),
            created_at=response.get("UserCreateDate"),
            last_modified_at=response.get("UserLastModifiedDate"),
        )

    def list_users(self, *, limit: int = 60, search: str = "") -> list[CognitoUser]:
        """List directory users, optionally narrowed by an email prefix.

        Cognito's ``Filter`` only supports prefix matching on a single
        attribute, so a broader search is applied client-side over the page
        that was fetched.
        """
        kwargs: dict[str, Any] = {
            "UserPoolId": self._config.user_pool_id,
            "Limit": min(max(limit, 1), 60),
        }
        if search:
            kwargs["Filter"] = f'email ^= "{search}"'

        response = self._call("list_users", **kwargs)
        users = []
        for item in response.get("Users", []):
            attributes = _attributes_to_dict(item.get("Attributes", []))
            users.append(
                CognitoUser(
                    username=item.get("Username", ""),
                    sub=attributes.get("sub", ""),
                    email=attributes.get("email", ""),
                    name=attributes.get("name") or attributes.get("given_name", ""),
                    enabled=bool(item.get("Enabled", True)),
                    status=item.get("UserStatus", ""),
                    created_at=item.get("UserCreateDate"),
                    last_modified_at=item.get("UserLastModifiedDate"),
                )
            )
        return users

    def list_groups(self) -> list[dict]:
        response = self._call("list_groups", UserPoolId=self._config.user_pool_id, Limit=60)
        return [
            {
                "name": group.get("GroupName", ""),
                "description": group.get("Description", ""),
            }
            for group in response.get("Groups", [])
        ]

    def list_users_in_group(self, group: str, *, limit: int = 60) -> list[str]:
        response = self._call(
            "list_users_in_group",
            UserPoolId=self._config.user_pool_id,
            GroupName=group,
            Limit=min(max(limit, 1), 60),
        )
        return [item.get("Username", "") for item in response.get("Users", [])]

    def groups_for_user(self, username: str) -> list[str]:
        response = self._call(
            "admin_list_groups_for_user",
            UserPoolId=self._config.user_pool_id,
            Username=username,
            Limit=60,
        )
        return [group.get("GroupName", "") for group in response.get("Groups", [])]

    # -- directory writes -------------------------------------------------

    def create_user(self, *, username: str, email: str, display_name: str = "", send_invite: bool = True) -> CognitoUser:
        """Invite a user. Cognito generates and emails the temporary password.

        Scrapos never chooses or sees a Cognito password, which is why
        AdminSetUserPassword is deliberately absent from the task role.
        """
        attributes = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ]
        if display_name:
            attributes.append({"Name": "name", "Value": display_name})

        response = self._call(
            "admin_create_user",
            UserPoolId=self._config.user_pool_id,
            Username=username,
            UserAttributes=attributes,
            DesiredDeliveryMediums=["EMAIL"],
            # SUPPRESS creates the account without emailing anyone, for when an
            # administrator wants to stage a user before inviting them.
            **({} if send_invite else {"MessageAction": "SUPPRESS"}),
        )

        item = response.get("User", {})
        found = _attributes_to_dict(item.get("Attributes", []))
        return CognitoUser(
            username=item.get("Username", username),
            sub=found.get("sub", ""),
            email=found.get("email", email),
            name=found.get("name", display_name),
            enabled=bool(item.get("Enabled", True)),
            status=item.get("UserStatus", ""),
            created_at=item.get("UserCreateDate"),
        )

    def resend_invite(self, username: str, email: str) -> None:
        self._call(
            "admin_create_user",
            UserPoolId=self._config.user_pool_id,
            Username=username,
            UserAttributes=[{"Name": "email", "Value": email}],
            MessageAction="RESEND",
            DesiredDeliveryMediums=["EMAIL"],
        )

    def enable_user(self, username: str) -> None:
        self._call("admin_enable_user", UserPoolId=self._config.user_pool_id, Username=username)

    def disable_user(self, username: str) -> None:
        self._call("admin_disable_user", UserPoolId=self._config.user_pool_id, Username=username)

    def add_user_to_group(self, username: str, group: str) -> None:
        self._call(
            "admin_add_user_to_group",
            UserPoolId=self._config.user_pool_id,
            Username=username,
            GroupName=group,
        )

    def remove_user_from_group(self, username: str, group: str) -> None:
        self._call(
            "admin_remove_user_from_group",
            UserPoolId=self._config.user_pool_id,
            Username=username,
            GroupName=group,
        )

    def reset_password(self, username: str) -> None:
        """Start the forgot-password flow; Cognito emails the code."""
        self._call(
            "admin_reset_user_password",
            UserPoolId=self._config.user_pool_id,
            Username=username,
        )

    def global_sign_out(self, username: str) -> None:
        self._call(
            "admin_user_global_sign_out",
            UserPoolId=self._config.user_pool_id,
            Username=username,
        )

    # -- diagnostics ------------------------------------------------------

    def connectivity(self) -> tuple[str, str]:
        """Cheap health probe for the dashboard status widget.

        Returns ``(state, detail)`` and never raises, so a Cognito outage
        degrades one card instead of the whole page.
        """
        if not self._config.is_configured:
            return "configuration_error", "Cognito settings are incomplete."
        try:
            self.list_groups()
        except CognitoPermissionDenied:
            return "permission_error", "The task role is missing a Cognito permission."
        except CognitoNotConfigured:
            return "configuration_error", "The configured user pool could not be found."
        except (CognitoUnavailable, TooManyAttempts):
            return "unavailable", "Cognito did not respond."
        except Exception:  # pragma: no cover - defensive
            logger.exception("cognito_request_failure operation=connectivity")
            return "unavailable", "Cognito did not respond."
        return "connected", "Cognito is reachable."


def _safe_operation_message(code: str) -> str:
    return {
        "UsernameExistsException": "That username already exists in the directory.",
        "InvalidParameterException": "Cognito rejected one of the supplied values.",
        "InvalidPasswordException": "The password does not meet the directory policy.",
        "AliasExistsException": "That email address is already in use.",
        "GroupExistsException": "That group already exists.",
    }.get(code, "The directory rejected this operation.")
