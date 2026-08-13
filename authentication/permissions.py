"""Server-side authorisation.

Every protected view is gated here. Navigation hiding in templates is
presentation only — it is never the thing that stops a request, and each
dashboard endpoint carries its own decorator or mixin.
"""

from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from . import audit
from .roles import ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_VIEWER, role_at_least  # noqa: F401


def _deny(request, required: str):
    audit.record(
        audit.PERMISSION_DENIED,
        request=request,
        target=request.path,
        required_role=required,
        actual_role=getattr(request.user, "role", "anonymous"),
    )
    raise PermissionDenied("You do not have permission to view this page.")


def login_required(view):
    """Redirect anonymous users to the Scrapos login page with a safe ``next``."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("authentication:login")
            return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
        return view(request, *args, **kwargs)

    return wrapper


def role_required(minimum: str):
    """Require at least ``minimum`` on the rank ladder.

    Anonymous users are redirected to sign in; authenticated users who are
    simply not allowed get a 403, and the denial is audited.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                login_url = reverse("authentication:login")
                return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
            if not request.user.has_role(minimum):
                return _deny(request, minimum)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


administrator_required = role_required(ROLE_ADMINISTRATOR)
editor_required = role_required(ROLE_EDITOR)


class RoleRequiredMixin:
    """Class-based-view equivalent of :func:`role_required`."""

    required_role = ROLE_VIEWER

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("authentication:login")
            return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
        if not request.user.has_role(self.required_role):
            return _deny(request, self.required_role)
        return super().dispatch(request, *args, **kwargs)


class AdministratorRequiredMixin(RoleRequiredMixin):
    required_role = ROLE_ADMINISTRATOR
