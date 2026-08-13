from authentication.roles import ROLE_ADMINISTRATOR, ROLE_EDITOR, role_at_least


def shell(request):
    """Shared chrome context for every page.

    ``current_user`` drives the sidebar identity block. The ``can_*`` flags only
    decide which navigation entries are drawn — every protected view enforces
    its own permission server-side, so hiding a link is never the control.
    """
    user = getattr(request, "user", None)
    authenticated = bool(user and user.is_authenticated)
    role = getattr(user, "role", "") if authenticated else ""

    return {
        "current_user": user if authenticated else None,
        "can_administer": authenticated and role_at_least(role, ROLE_ADMINISTRATOR),
        "can_edit": authenticated and role_at_least(role, ROLE_EDITOR),
    }
