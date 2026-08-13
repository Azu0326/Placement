"""The custom Scrapos administration interface.

Every view here is gated server-side by :class:`RoleRequiredMixin` or
:func:`role_required`; the sidebar only hides links the user cannot use, which
is presentation, not authorisation. All state-changing operations are POST with
CSRF protection — nothing mutates on a GET.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from authentication import audit
from authentication.conf import get_bootstrap_config, get_cognito_config
from authentication.exceptions import ScraposAuthError
from authentication.models import ScraposUser
from authentication.permissions import (
    AdministratorRequiredMixin,
    RoleRequiredMixin,
    role_required,
)
from authentication.roles import (
    ASSIGNABLE_ROLES,
    ROLE_ADMINISTRATOR,
    ROLE_VIEWER,
    group_for_role,
)
from authentication.services.cognito_service import CognitoService

from . import services

logger = logging.getLogger("scrapos.auth")


class DashboardBaseView(RoleRequiredMixin, TemplateView):
    """Shared chrome for the administration screens."""

    required_role = ROLE_VIEWER
    nav_key = ""
    crumb = ""
    page_title = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "nav_key": self.nav_key,
                "nav_group": "g-admin",
                "crumb": self.crumb,
                "page_title": self.page_title,
            }
        )
        return ctx


class DashboardHomeView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/home.html"
    nav_key = "admin_home"
    crumb = "Administration / Dashboard"
    page_title = "Administration"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rows, state, detail = services.list_directory_users()
        status_label, tone = services.STATUS_LABELS.get(state, ("Unavailable", "err"))

        ctx.update(
            {
                "metrics": services.dashboard_metrics(rows, state=state),
                "recent_logins": services.recent_logins(),
                "cognito_state": state,
                "cognito_status_label": status_label,
                "cognito_status_tone": tone,
                "cognito_status_detail": detail,
                # Configuration metadata, not a secret. The client secret and
                # every AWS credential stay server-side.
                "cognito_pool_id": get_cognito_config().user_pool_id,
                "cognito_region": get_cognito_config().region,
                "bootstrap_enabled": get_bootstrap_config().is_configured,
            }
        )
        return ctx


class UserListView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/users.html"
    nav_key = "admin_users"
    crumb = "Administration / Users"
    page_title = "Users"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        search = (self.request.GET.get("q") or "").strip()
        role_filter = (self.request.GET.get("role") or "").strip()
        status_filter = (self.request.GET.get("status") or "").strip()
        source_filter = (self.request.GET.get("source") or "").strip()

        rows, state, detail = services.list_directory_users(search=search)

        if role_filter:
            rows = [r for r in rows if r.role == role_filter]
        if status_filter == "active":
            rows = [r for r in rows if r.enabled]
        elif status_filter == "disabled":
            rows = [r for r in rows if not r.enabled]
        if source_filter:
            rows = [r for r in rows if r.auth_source == source_filter]

        ctx.update(
            {
                "rows": rows,
                "search": search,
                "role_filter": role_filter,
                "status_filter": status_filter,
                "source_filter": source_filter,
                "cognito_state": state,
                "cognito_status_detail": detail,
                "assignable_roles": ASSIGNABLE_ROLES,
            }
        )
        return ctx


class UserDetailView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/user_detail.html"
    nav_key = "admin_users"
    crumb = "Administration / Users"
    page_title = "User"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        username = kwargs["username"]
        row, state, detail = services.get_directory_user(username)
        if row is None:
            raise Http404("No such user.")

        ctx.update(
            {
                "row": row,
                "crumb": f"Administration / Users / {row.username}",
                "page_title": row.display_name or row.username,
                "cognito_state": state,
                "cognito_status_detail": detail,
                "assignable_roles": ASSIGNABLE_ROLES,
                "is_self": row.username == self.request.user.username,
            }
        )
        return ctx


class UserCreateView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/user_new.html"
    nav_key = "admin_users"
    crumb = "Administration / Users / Invite"
    page_title = "Invite user"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["assignable_roles"] = ASSIGNABLE_ROLES
        ctx["errors"] = kwargs.get("errors", [])
        return ctx

    def post(self, request, *args, **kwargs):
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        display_name = (request.POST.get("display_name") or "").strip()
        role = (request.POST.get("role") or ROLE_VIEWER).strip()

        errors = []
        if not username:
            errors.append("A username is required.")
        if not email:
            errors.append("An email address is required.")
        if role not in ASSIGNABLE_ROLES:
            errors.append("Choose a valid role.")
        if _is_bootstrap_username(username):
            # The bootstrap account must never be created in the directory.
            errors.append("That username is reserved and cannot be created in Cognito.")

        if errors:
            return self.render_to_response(self.get_context_data(errors=errors))

        service = CognitoService()
        try:
            service.create_user(username=username, email=email, display_name=display_name)
            group = group_for_role(role)
            if group:
                service.add_user_to_group(username, group)
        except ScraposAuthError as exc:
            return self.render_to_response(self.get_context_data(errors=[str(exc)]))

        audit.record(
            audit.USER_CREATED,
            request=request,
            target=username,
            role=role,
        )
        messages.success(request, f"Invited {username}. Cognito has emailed their temporary password.")
        return redirect(reverse("dashboard:user_detail", args=[username]))


class GroupListView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/groups.html"
    nav_key = "admin_groups"
    crumb = "Administration / Roles"
    page_title = "Roles and groups"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        config = get_cognito_config()
        service = CognitoService()

        mapped = []
        detail = ""
        state = "connected"
        for role, group in (
            ("administrator", config.group_admin),
            ("editor", config.group_editor),
            ("viewer", config.group_viewer),
        ):
            members: list[str] = []
            try:
                members = service.list_users_in_group(group) if service.is_configured else []
            except ScraposAuthError as exc:
                state, detail = services._state_for(exc)
            mapped.append({"role": role, "group": group, "members": members, "count": len(members)})

        ctx.update(
            {
                "mapped_groups": mapped,
                "cognito_state": state if service.is_configured else "configuration_error",
                "cognito_status_detail": detail,
            }
        )
        return ctx


class AuditListView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/audit.html"
    nav_key = "admin_audit"
    crumb = "Administration / Audit"
    page_title = "Audit log"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        action = (self.request.GET.get("action") or "").strip()
        ctx["events"] = services.recent_events(limit=100, action=action)
        ctx["action_filter"] = action
        ctx["actions"] = [
            audit.LOGIN_SUCCESS,
            audit.LOGIN_FAILURE,
            audit.BOOTSTRAP_LOGIN,
            audit.LOGOUT,
            audit.LOGIN_THROTTLED,
            audit.PERMISSION_DENIED,
            audit.SESSION_REVOKED,
            audit.USER_CREATED,
            audit.USER_ENABLED,
            audit.USER_DISABLED,
            audit.USER_ROLE_CHANGED,
            audit.PASSWORD_RESET_INITIATED,
        ]
        return ctx


class SettingsView(AdministratorRequiredMixin, DashboardBaseView):
    template_name = "dashboard/settings.html"
    nav_key = "admin_settings"
    crumb = "Administration / Settings"
    page_title = "Settings"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        config = get_cognito_config()
        boot = get_bootstrap_config()
        state, label, tone, detail = services.cognito_status()

        ctx.update(
            {
                "cognito_state": state,
                "cognito_status_label": label,
                "cognito_status_tone": tone,
                "cognito_status_detail": detail,
                # Operational metadata only. Nothing here is a secret: the
                # client secret, task-role credentials and tokens are never
                # placed in a template context.
                "config_rows": [
                    ("AWS region", config.region or "—"),
                    ("User pool", config.user_pool_id or "—"),
                    ("App client", config.client_id or "—"),
                    ("Hosted UI domain", config.domain or "—"),
                    ("Redirect URL", config.redirect_uri or "—"),
                    ("Administrator group", config.group_admin),
                    ("Editor group", config.group_editor),
                    ("Viewer group", config.group_viewer),
                ],
                "hosted_ui_enabled": config.hosted_ui_enabled,
                "bootstrap_enabled": boot.is_configured,
                "bootstrap_username": boot.username if boot.is_configured else "",
                "local_user_count": ScraposUser.objects.count(),
            }
        )
        return ctx


@require_POST
@role_required(ROLE_ADMINISTRATOR)
def user_action(request, username: str):
    """Enable, disable, change role, or start a password reset.

    POST-only and CSRF-protected. Safeguards live here rather than in the
    template so they cannot be skipped by posting directly.
    """
    action = (request.POST.get("action") or "").strip()
    service = CognitoService()

    if _is_bootstrap_username(username):
        # The bootstrap account has no directory record to act on, and must not
        # be removable or disableable from the UI.
        messages.error(request, "The bootstrap superadmin is managed through its secret, not from here.")
        return redirect(reverse("dashboard:users"))

    is_self = username == request.user.username

    try:
        if action == "disable":
            if is_self:
                messages.error(request, "You cannot disable your own account.")
                return _back(request, username)
            if _would_remove_last_administrator(service, username):
                messages.error(
                    request,
                    "This is the last administrator. Promote someone else before disabling them.",
                )
                return _back(request, username)
            service.disable_user(username)
            audit.record(audit.USER_DISABLED, request=request, target=username)
            ScraposUser.objects.filter(username=username).update(is_active=False)
            messages.success(request, f"Disabled {username}.")

        elif action == "enable":
            service.enable_user(username)
            audit.record(audit.USER_ENABLED, request=request, target=username)
            ScraposUser.objects.filter(username=username).update(is_active=True)
            messages.success(request, f"Enabled {username}.")

        elif action == "set_role":
            role = (request.POST.get("role") or "").strip()
            if role not in ASSIGNABLE_ROLES:
                messages.error(request, "Choose a valid role.")
                return _back(request, username)
            if is_self and role != ROLE_ADMINISTRATOR:
                messages.error(request, "You cannot remove your own administrator access.")
                return _back(request, username)
            if (
                role != ROLE_ADMINISTRATOR
                and _would_remove_last_administrator(service, username)
            ):
                messages.error(
                    request,
                    "This is the last administrator. Promote someone else before demoting them.",
                )
                return _back(request, username)

            config = get_cognito_config()
            target_group = group_for_role(role, config)
            for candidate in (config.group_admin, config.group_editor, config.group_viewer):
                if candidate != target_group:
                    try:
                        service.remove_user_from_group(username, candidate)
                    except ScraposAuthError:
                        # Removing a group the user is not in is not a failure.
                        pass
            if target_group:
                service.add_user_to_group(username, target_group)

            audit.record(audit.USER_ROLE_CHANGED, request=request, target=username, role=role)
            ScraposUser.objects.filter(username=username).update(role=role)
            messages.success(request, f"{username} is now a {role}.")

        elif action == "reset_password":
            service.reset_password(username)
            audit.record(audit.PASSWORD_RESET_INITIATED, request=request, target=username)
            messages.success(request, f"Cognito has emailed {username} a password reset code.")

        elif action == "resend_invite":
            email = (request.POST.get("email") or "").strip()
            if not email:
                messages.error(request, "An email address is required to resend an invitation.")
                return _back(request, username)
            service.resend_invite(username, email)
            audit.record(audit.USER_CREATED, request=request, target=username, resent=True)
            messages.success(request, f"Resent the invitation to {username}.")

        else:
            messages.error(request, "Unknown action.")

    except ScraposAuthError as exc:
        messages.error(request, str(exc))

    return _back(request, username)


def _back(request, username: str):
    if request.POST.get("return") == "list":
        return redirect(reverse("dashboard:users"))
    return redirect(reverse("dashboard:user_detail", args=[username]))


def _is_bootstrap_username(username: str) -> bool:
    from authentication import bootstrap

    return bootstrap.matches_username(username)


def _would_remove_last_administrator(service: CognitoService, username: str) -> bool:
    """True when ``username`` is the only Cognito administrator left.

    The bootstrap account is not counted: it may be disabled entirely in a
    hardened environment, so it cannot be relied on as the safety net.
    """
    config = get_cognito_config()
    try:
        admins = set(service.list_users_in_group(config.group_admin))
    except ScraposAuthError:
        # If the directory cannot be read, refuse the destructive change.
        return True
    return admins == {username}


def permission_denied_view(request, exception):  # pragma: no cover - wired in config.urls
    return render(request, "403.html", status=403)
