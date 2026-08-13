"""Application-level authentication errors.

Everything AWS-specific is translated into one of these before it leaves
``authentication.services.cognito_service``, so views and templates never see a
botocore exception and never risk rendering an AWS error string to a browser.
"""

from __future__ import annotations


class ScraposAuthError(Exception):
    """Base class for every authentication or Cognito failure."""


class AuthenticationFailed(ScraposAuthError):
    """Credentials were rejected.

    Deliberately covers unknown user, wrong password, disabled account and
    "password reset required" alike: the caller must not be able to tell those
    apart from the response, only from the server-side log.
    """

    def __init__(self, message: str = "Invalid username or password.", *, reason: str = "invalid_credentials"):
        super().__init__(message)
        self.reason = reason


class UserDisabled(AuthenticationFailed):
    def __init__(self, message: str = "Invalid username or password."):
        super().__init__(message, reason="user_disabled")


class PasswordResetRequired(AuthenticationFailed):
    def __init__(self, message: str = "Invalid username or password."):
        super().__init__(message, reason="password_reset_required")


class UserNotConfirmed(AuthenticationFailed):
    def __init__(self, message: str = "Invalid username or password."):
        super().__init__(message, reason="user_not_confirmed")


class ChallengeRequired(ScraposAuthError):
    """Cognito wants an additional step Scrapos does not drive itself.

    Raised for NEW_PASSWORD_REQUIRED, MFA and similar. The user is told to
    finish setup elsewhere rather than being silently let in.
    """

    def __init__(self, challenge: str):
        super().__init__(f"Additional sign-in step required: {challenge}")
        self.challenge = challenge


class TooManyAttempts(ScraposAuthError):
    """Local brute-force throttle tripped, or Cognito reported rate limiting."""

    def __init__(self, message: str = "Too many sign-in attempts. Please try again later."):
        super().__init__(message)


class CognitoNotConfigured(ScraposAuthError):
    """Cognito settings are missing or incomplete, so it cannot be used."""

    def __init__(self, message: str = "Sign-in is temporarily unavailable. Please contact an administrator."):
        super().__init__(message)


class CognitoUnavailable(ScraposAuthError):
    """Cognito could not be reached, or returned a server-side failure."""

    def __init__(self, message: str = "Sign-in is temporarily unavailable. Please try again shortly."):
        super().__init__(message)


class CognitoPermissionDenied(ScraposAuthError):
    """The task role is missing an IAM permission the operation needs."""

    def __init__(self, message: str = "Scrapos is not permitted to perform this directory operation."):
        super().__init__(message)


class CognitoOperationFailed(ScraposAuthError):
    """An administrative Cognito call failed for an expected, reportable reason."""


class InvalidToken(ScraposAuthError):
    """A Cognito token failed validation and must not be trusted."""
