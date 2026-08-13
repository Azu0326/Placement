"""Scrapos roles and the Cognito groups they come from.

Authorisation is a rank ladder: viewer < editor < administrator < superadmin.
``superadmin`` is reserved for the bootstrap account and is never granted by a
Cognito group, so no directory change can mint one.
"""

from __future__ import annotations

ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_ADMINISTRATOR = "administrator"
ROLE_SUPERADMIN = "superadmin"

ROLE_CHOICES = [
    (ROLE_VIEWER, "Viewer"),
    (ROLE_EDITOR, "Editor"),
    (ROLE_ADMINISTRATOR, "Administrator"),
    (ROLE_SUPERADMIN, "Bootstrap superadmin"),
]

_RANK = {
    ROLE_VIEWER: 10,
    ROLE_EDITOR: 20,
    ROLE_ADMINISTRATOR: 30,
    ROLE_SUPERADMIN: 40,
}

#: Roles an administrator may hand out from the dashboard. Administrators
#: cannot create another superadmin, and cannot grant a role above their own.
ASSIGNABLE_ROLES = [ROLE_VIEWER, ROLE_EDITOR, ROLE_ADMINISTRATOR]

AUTH_SOURCE_COGNITO = "cognito"
AUTH_SOURCE_BOOTSTRAP = "bootstrap"

AUTH_SOURCE_CHOICES = [
    (AUTH_SOURCE_COGNITO, "Cognito"),
    (AUTH_SOURCE_BOOTSTRAP, "Bootstrap"),
]


def rank(role: str) -> int:
    return _RANK.get(role, 0)


def role_at_least(role: str, minimum: str) -> bool:
    return rank(role) >= rank(minimum)


def role_from_groups(groups, config=None) -> str:
    """Highest Scrapos role implied by a user's Cognito group memberships.

    A user in no mapped group is a viewer: sign-in alone never confers
    write access.
    """
    from .conf import get_cognito_config

    config = config or get_cognito_config()
    mapping = config.role_groups
    best = ROLE_VIEWER
    for group in groups or ():
        candidate = mapping.get(group)
        if candidate and rank(candidate) > rank(best):
            best = candidate
    return best


def group_for_role(role: str, config=None) -> str | None:
    """Inverse of :func:`role_from_groups` for a single assignable role."""
    from .conf import get_cognito_config

    config = config or get_cognito_config()
    for group, mapped in config.role_groups.items():
        if mapped == role:
            return group
    return None
