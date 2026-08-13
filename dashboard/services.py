"""Read models for the administration screens.

Views stay thin: they check permission, call one of these functions, and render.
Cognito is reached only through ``CognitoService``, and every call here degrades
to a safe empty result plus a status string rather than raising into a template.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from authentication.conf import get_bootstrap_config, get_cognito_config
from authentication.exceptions import ScraposAuthError
from authentication.models import AuditEvent, ScraposUser
from authentication.roles import (
    AUTH_SOURCE_BOOTSTRAP,
    ROLE_ADMINISTRATOR,
    ROLE_EDITOR,
    ROLE_VIEWER,
    role_from_groups,
)
from authentication.services.cognito_service import CognitoService
from authentication.services.identity_service import (
    local_user_for_cognito_username,
    local_users_by_cognito_username,
)

#: Human labels for the Cognito status widget.
STATUS_LABELS = {
    "connected": ("Connected", "ok"),
    "configuration_error": ("Configuration Error", "warn"),
    "permission_error": ("AWS Permission Error", "warn"),
    "unavailable": ("Unavailable", "err"),
}


@dataclass
class DirectoryUser:
    """One row of the user table, merged from Cognito and the local mirror."""

    username: str
    email: str = ""
    display_name: str = ""
    role: str = ROLE_VIEWER
    auth_source: str = "cognito"
    enabled: bool = True
    status: str = ""
    created_at: object = None
    last_login: object = None
    groups: list[str] = field(default_factory=list)
    is_bootstrap: bool = False

    @property
    def source_label(self) -> str:
        return "Bootstrap Superadmin" if self.is_bootstrap else "Cognito"

    @property
    def status_label(self) -> str:
        if self.is_bootstrap:
            return "Active"
        return "Active" if self.enabled else "Disabled"

    @property
    def initials(self) -> str:
        source = (self.display_name or self.email or self.username).strip()
        parts = [p for p in source.replace(".", " ").replace("@", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()


def bootstrap_row() -> DirectoryUser | None:
    """The bootstrap account, shown so administrators know it exists.

    It is listed from configuration rather than from the directory, which is
    the point: it is not in Cognito and must never be looked up there.
    """
    config = get_bootstrap_config()
    if not config.is_configured:
        return None
    local = ScraposUser.objects.filter(username=config.username).first()
    return DirectoryUser(
        username=config.username,
        email="",
        display_name="Bootstrap Superadmin",
        role="superadmin",
        auth_source=AUTH_SOURCE_BOOTSTRAP,
        enabled=True,
        status="BOOTSTRAP",
        created_at=local.created_at if local else None,
        last_login=local.last_login if local else None,
        is_bootstrap=True,
    )


def list_directory_users(*, search: str = "", service: CognitoService | None = None):
    """Merged user list plus a Cognito status string.

    Returns ``(rows, state, detail)``. A Cognito failure yields the bootstrap
    row alone rather than an error page, so an administrator can still sign in
    and diagnose.
    """
    service = service or CognitoService()
    config = get_cognito_config()
    rows: list[DirectoryUser] = []

    boot = bootstrap_row()
    if boot is not None:
        rows.append(boot)

    if not service.is_configured:
        return rows, "configuration_error", "Cognito settings are incomplete."

    try:
        cognito_users = service.list_users(search=search)
        group_members = {}
        for group in (config.group_admin, config.group_editor, config.group_viewer):
            try:
                group_members[group] = set(service.list_users_in_group(group))
            except ScraposAuthError:
                group_members[group] = set()
    except ScraposAuthError as exc:
        state, detail = _state_for(exc)
        return rows, state, detail

    # Federated records are called "Google_1234…" in Cognito but not in Scrapos,
    # so the join goes through the recorded linked identities.
    locals_by_username = local_users_by_cognito_username()

    for user in cognito_users:
        groups = [name for name, members in group_members.items() if user.username in members]
        local = locals_by_username.get(user.username)
        rows.append(
            DirectoryUser(
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                role=role_from_groups(groups, config),
                auth_source="cognito",
                enabled=user.enabled,
                status=user.status,
                created_at=user.created_at,
                last_login=local.last_login if local else None,
                groups=groups,
            )
        )

    return rows, "connected", "Cognito is reachable."


def get_directory_user(username: str, *, service: CognitoService | None = None):
    """One user for the detail page, or ``None`` when it is not in Cognito."""
    boot = bootstrap_row()
    if boot is not None and username == boot.username:
        return boot, "connected", ""

    service = service or CognitoService()
    config = get_cognito_config()
    if not service.is_configured:
        return None, "configuration_error", "Cognito settings are incomplete."

    try:
        user = service.get_user(username)
        groups = service.groups_for_user(username)
    except ScraposAuthError as exc:
        state, detail = _state_for(exc)
        return None, state, detail

    local = local_user_for_cognito_username(username)
    return (
        DirectoryUser(
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            role=role_from_groups(groups, config),
            auth_source="cognito",
            enabled=user.enabled,
            status=user.status,
            created_at=user.created_at,
            last_login=local.last_login if local else None,
            groups=groups,
        ),
        "connected",
        "",
    )


def dashboard_metrics(rows, *, state: str):
    """Counters for the dashboard cards."""
    cognito_rows = [r for r in rows if not r.is_bootstrap]
    return {
        "total_users": len(rows),
        "active_users": sum(1 for r in cognito_rows if r.enabled),
        "disabled_users": sum(1 for r in cognito_rows if not r.enabled),
        "administrators": sum(1 for r in rows if r.role in {ROLE_ADMINISTRATOR, "superadmin"}),
        "editors": sum(1 for r in rows if r.role == ROLE_EDITOR),
        "viewers": sum(1 for r in cognito_rows if r.role == ROLE_VIEWER),
        "directory_reachable": state == "connected",
    }


def recent_logins(limit: int = 8):
    from authentication import audit

    return AuditEvent.objects.filter(
        action__in=[audit.LOGIN_SUCCESS, audit.BOOTSTRAP_LOGIN]
    )[:limit]


def recent_events(limit: int = 50, action: str = ""):
    queryset = AuditEvent.objects.all()
    if action:
        queryset = queryset.filter(action=action)
    return queryset[:limit]


def cognito_status(service: CognitoService | None = None):
    """``(state, label, tone, detail)`` for the integration status widget."""
    service = service or CognitoService()
    state, detail = service.connectivity()
    label, tone = STATUS_LABELS.get(state, ("Unavailable", "err"))
    return state, label, tone, detail


def _state_for(exc: Exception) -> tuple[str, str]:
    from authentication.exceptions import (
        CognitoNotConfigured,
        CognitoPermissionDenied,
    )

    if isinstance(exc, CognitoPermissionDenied):
        return "permission_error", "The task role is missing a Cognito permission."
    if isinstance(exc, CognitoNotConfigured):
        return "configuration_error", "Cognito settings are incomplete."
    return "unavailable", "Cognito did not respond."
