from . import data


def shell(request):
    """Shared chrome context for every page."""
    return {
        "demo_user": data.DEMO_USER,
    }
