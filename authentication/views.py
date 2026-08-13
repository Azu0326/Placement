"""Sign-in, sign-out and the hosted-UI callback.

The login view keeps no branching knowledge of providers: it collects
credentials, hands them to ``auth_service`` and renders whatever safe message
comes back. Failure messages are deliberately uniform so a response cannot be
used to discover whether a username exists.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import views as auth_views  # noqa: F401  (kept for URL reversing parity)
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from . import audit, oidc
from .conf import get_bootstrap_config, get_cognito_config
from .exceptions import (
    AuthenticationFailed,
    ChallengeRequired,
    CognitoNotConfigured,
    CognitoPermissionDenied,
    CognitoUnavailable,
    InvalidToken,
    ScraposAuthError,
    TooManyAttempts,
)
from .forms import LoginForm
from .services import auth_service
from .services.cognito_service import CognitoService

logger = logging.getLogger("scrapos.auth")

GENERIC_FAILURE = "Invalid username or password."


def safe_next(request, candidate: str | None) -> str:
    """Return ``candidate`` only if it points back at this site.

    Blocks open redirects: an attacker-supplied ``?next=https://evil.example``
    is discarded in favour of the default landing page.
    """
    default = settings.LOGIN_REDIRECT_URL
    if not candidate:
        return default
    if url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


def _login_context(request, form, error: str = "", **extra):
    cognito = get_cognito_config()
    context = {
        "form": form,
        "error": error,
        "next": request.POST.get("next") or request.GET.get("next") or "",
        "hosted_ui_enabled": cognito.hosted_ui_enabled,
        "page_title": "Sign in",
        "revoked": request.GET.get("revoked") == "1",
    }
    context.update(extra)
    return context


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(safe_next(request, request.GET.get("next")))

    if request.method == "GET":
        return render(request, "authentication/login.html", _login_context(request, LoginForm()))

    form = LoginForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "authentication/login.html",
            _login_context(request, form, GENERIC_FAILURE),
            status=400,
        )

    username = form.cleaned_data["username"]
    password = form.cleaned_data["password"]

    try:
        user = auth_service.authenticate_credentials(request, username, password)
    except TooManyAttempts as exc:
        return _fail(request, form, str(exc), status=429)
    except AuthenticationFailed:
        return _fail(request, form, GENERIC_FAILURE, status=401)
    except ChallengeRequired:
        return _fail(
            request,
            form,
            "Your account needs to finish setup before you can sign in. "
            "Contact an administrator.",
            status=401,
        )
    except (CognitoNotConfigured, CognitoUnavailable, CognitoPermissionDenied) as exc:
        return _fail(request, form, str(exc), status=503)
    except InvalidToken:
        logger.warning("authentication_failure reason=invalid_token")
        return _fail(request, form, GENERIC_FAILURE, status=401)
    except ScraposAuthError:
        logger.exception("authentication_failure reason=unexpected")
        return _fail(request, form, "Sign-in is temporarily unavailable.", status=503)

    auth_service.establish_session(request, user)
    auth_service.record_login_success(request, user)
    return redirect(safe_next(request, request.POST.get("next")))


def _fail(request, form, message, *, status):
    # Never re-render the submitted password.
    form.data = form.data.copy()
    form.data["password"] = ""
    return render(
        request,
        "authentication/login.html",
        _login_context(request, form, message),
        status=status,
    )


@never_cache
@require_POST
@csrf_protect
def logout_view(request):
    """End the server session. POST-only so a link cannot sign someone out."""
    user = request.user
    if user.is_authenticated:
        audit.record(
            audit.LOGOUT,
            request=request,
            actor=user.username,
            actor_auth_source=user.auth_source,
        )
    was_cognito = user.is_authenticated and user.is_cognito
    auth_service.end_session(request)

    config = get_cognito_config()
    if was_cognito and config.hosted_ui_enabled and config.logout_redirect_uri:
        # Also drop the Cognito session, otherwise the hosted UI would sign the
        # user straight back in on the next attempt.
        return HttpResponseRedirect(oidc.logout_url(config, config.logout_redirect_uri))
    return redirect(settings.LOGOUT_REDIRECT_URL)


@never_cache
@require_http_methods(["GET", "POST"])
def oauth_start(request):
    """Kick off the hosted-UI authorization-code flow."""
    config = get_cognito_config()
    if not config.hosted_ui_enabled:
        return redirect(reverse("authentication:login"))
    next_url = safe_next(request, request.GET.get("next"))
    return HttpResponseRedirect(oidc.begin(request, config, next_url=next_url))


@never_cache
@require_http_methods(["GET"])
def oauth_callback(request):
    config = get_cognito_config()
    form = LoginForm()

    if not config.hosted_ui_enabled:
        return _fail(request, form, "Single sign-on is not configured.", status=503)

    if request.GET.get("error"):
        # Cognito reports its own failure here; log the code, show nothing.
        logger.warning("authentication_failure reason=oidc_provider_error")
        return _fail(request, form, GENERIC_FAILURE, status=401)

    try:
        nonce, verifier, next_url = oidc.consume(request, request.GET.get("state", ""))
    except AuthenticationFailed as exc:
        return _fail(request, form, str(exc), status=400)

    code = request.GET.get("code", "")
    if not code:
        return _fail(request, form, GENERIC_FAILURE, status=400)

    try:
        service = CognitoService(config)
        tokens = service.exchange_code(code, config.redirect_uri, verifier)
        claims = tokens_claims(tokens.id_token, config, nonce)
        user = auth_service.sync_user_from_claims(claims, config=config)
    except (AuthenticationFailed, InvalidToken):
        audit.record(audit.LOGIN_FAILURE, request=request, reason="oidc_callback_rejected")
        return _fail(request, form, GENERIC_FAILURE, status=401)
    except ScraposAuthError as exc:
        return _fail(request, form, str(exc), status=503)

    auth_service.establish_session(request, user)
    auth_service.record_login_success(request, user)
    return redirect(safe_next(request, next_url))


def tokens_claims(id_token: str, config, nonce: str):
    from .tokens import verify_id_token

    return verify_id_token(id_token, config, nonce=nonce or None)


def bootstrap_enabled() -> bool:
    return get_bootstrap_config().is_configured
