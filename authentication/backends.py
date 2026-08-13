"""Session user loading.

Credential verification deliberately does *not* live in a Django
authentication backend. ``authentication.services.auth_service`` owns provider
selection so there is exactly one place that decides between the bootstrap
account and Cognito; a backend chain would let any future ``authenticate()``
call re-open that decision.

This backend therefore only answers "which user does this session belong to",
and refuses to load a deactivated one.
"""

from __future__ import annotations

from django.contrib.auth.backends import BaseBackend

from .models import ScraposUser


class ScraposSessionBackend(BaseBackend):
    def authenticate(self, request, **kwargs):
        # No credential path here on purpose — see the module docstring.
        return None

    def get_user(self, user_id):
        user = ScraposUser.objects.filter(pk=user_id).first()
        if user is None or not user.is_active:
            # A user disabled mid-session becomes anonymous on the next request.
            return None
        return user
