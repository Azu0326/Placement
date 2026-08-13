"""Request-level authentication enforcement.

Two concerns, deliberately separate from the health check middleware that runs
before them:

* :class:`LoginRequiredMiddleware` closes the whole application by default, so
  a new page is private unless its path is explicitly public. The existing
  frontend screens became protected without touching twenty view classes.
* :class:`CognitoSessionRevalidationMiddleware` periodically re-checks that a
  signed-in Cognito user is still enabled, so disabling someone in the
  directory ends their Scrapos session without waiting for it to expire.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from . import audit
from .exceptions import ScraposAuthError
from .roles import AUTH_SOURCE_COGNITO
from .services.auth_service import SESSION_REVALIDATE_AT, end_session

logger = logging.getLogger("scrapos.auth")


class LoginRequiredMiddleware:
    """Require a session for everything outside the public allow-list."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _public_prefixes(self) -> tuple[str, ...]:
        static_url = settings.STATIC_URL or "/static/"
        if not static_url.startswith("/"):
            static_url = "/" + static_url
        return (
            "/login",
            "/logout",
            "/auth/",
            "/healthz",
            static_url,
        ) + tuple(getattr(settings, "SCRAPOS_PUBLIC_PATH_PREFIXES", ()))

    def __call__(self, request):
        if request.user.is_authenticated or request.path.startswith(self._public_prefixes()):
            return self.get_response(request)

        login_url = reverse("authentication:login")
        if request.path == login_url:
            return self.get_response(request)

        return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")


class CognitoSessionRevalidationMiddleware:
    """Re-check a Cognito user's directory status on a timer.

    Fails open on a Cognito outage: a directory that cannot be reached must not
    log every signed-in administrator out, which is precisely when they might
    need the dashboard. A genuinely disabled user is still caught by the next
    successful revalidation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.auth_source == AUTH_SOURCE_COGNITO
            and self._due(request)
        ):
            if not self._still_valid(request, user):
                return redirect(f"{reverse('authentication:login')}?{urlencode({'revoked': '1'})}")
        return self.get_response(request)

    def _due(self, request) -> bool:
        due_at = request.session.get(SESSION_REVALIDATE_AT)
        if due_at is None:
            return True
        try:
            return timezone.now().timestamp() >= float(due_at)
        except (TypeError, ValueError):
            return True

    def _still_valid(self, request, user) -> bool:
        from .services.cognito_service import CognitoService

        interval = getattr(settings, "SCRAPOS_COGNITO_REVALIDATE_SECONDS", 300)
        try:
            service = CognitoService()
            if not service.is_configured:
                return True
            directory_user = service.get_user(user.username)
        except ScraposAuthError as exc:
            logger.warning("cognito_revalidation_skipped reason=%s", type(exc).__name__)
            # Push the next attempt out so an outage is not re-probed per request.
            request.session[SESSION_REVALIDATE_AT] = timezone.now().timestamp() + interval
            return True

        if not directory_user.enabled:
            audit.record(
                audit.SESSION_REVOKED,
                request=request,
                actor=user.username,
                actor_auth_source=user.auth_source,
                reason="disabled_in_directory",
            )
            user.is_active = False
            user.save(update_fields=["is_active", "updated_at"])
            end_session(request)
            return False

        request.session[SESSION_REVALIDATE_AT] = timezone.now().timestamp() + interval
        return True
