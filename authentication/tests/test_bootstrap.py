"""The bootstrap superadmin path."""

from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.urls import reverse

from authentication import bootstrap
from authentication.exceptions import AuthenticationFailed
from authentication.models import AuditEvent, LoginAttempt, ScraposUser
from authentication.roles import AUTH_SOURCE_BOOTSTRAP, ROLE_SUPERADMIN

from .factories import COGNITO_SETTINGS

PASSWORD = "correct-horse-battery-staple-42"

BOOTSTRAP_SETTINGS = {
    "SCRAPOS_BOOTSTRAP_ADMIN_ENABLED": True,
    "SCRAPOS_SUPERADMIN_USERNAME": "superadmin",
    "SCRAPOS_SUPERADMIN_PASSWORD_HASH": make_password(PASSWORD),
}


@override_settings(**BOOTSTRAP_SETTINGS)
class BootstrapAuthenticationTests(TestCase):
    def test_valid_credentials_create_a_bootstrap_user(self):
        user = bootstrap.authenticate("superadmin", PASSWORD)

        self.assertEqual(user.username, "superadmin")
        self.assertEqual(user.auth_source, AUTH_SOURCE_BOOTSTRAP)
        self.assertEqual(user.role, ROLE_SUPERADMIN)
        self.assertIsNone(user.cognito_sub)

    def test_no_password_is_ever_stored_locally(self):
        user = bootstrap.authenticate("superadmin", PASSWORD)
        self.assertFalse(user.has_usable_password())

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(AuthenticationFailed):
            bootstrap.authenticate("superadmin", "not-the-password")

    def test_username_match_is_case_insensitive(self):
        self.assertTrue(bootstrap.matches_username("SuperAdmin"))
        self.assertTrue(bootstrap.matches_username("  superadmin  "))

    def test_other_usernames_are_not_the_bootstrap_account(self):
        for candidate in ["admin", "superadmin2", "super", "", None]:
            self.assertFalse(bootstrap.matches_username(candidate), candidate)

    def test_disabled_bootstrap_never_matches(self):
        with override_settings(SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False):
            self.assertFalse(bootstrap.matches_username("superadmin"))
            with self.assertRaises(AuthenticationFailed):
                bootstrap.authenticate("superadmin", PASSWORD)

    def test_plaintext_hash_setting_fails_closed(self):
        with override_settings(SCRAPOS_SUPERADMIN_PASSWORD_HASH=PASSWORD):
            self.assertFalse(bootstrap.verify_password(PASSWORD))

    def test_drifted_row_is_repaired_on_login(self):
        ScraposUser.objects.create_user(
            username="superadmin",
            auth_source="cognito",
            role="viewer",
            is_active=False,
            cognito_sub="should-not-be-here",
        )

        user = bootstrap.authenticate("superadmin", PASSWORD)

        self.assertEqual(user.auth_source, AUTH_SOURCE_BOOTSTRAP)
        self.assertEqual(user.role, ROLE_SUPERADMIN)
        self.assertTrue(user.is_active)
        self.assertIsNone(user.cognito_sub)


@override_settings(**{**BOOTSTRAP_SETTINGS, **COGNITO_SETTINGS})
class BootstrapLoginViewTests(TestCase):
    def test_bootstrap_signs_in_through_the_shared_login_form(self):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": PASSWORD},
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), ScraposUser.objects.get().pk)

    def test_bootstrap_login_is_audited_distinctly(self):
        self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": PASSWORD},
        )

        event = AuditEvent.objects.get(action="bootstrap_admin_login")
        self.assertEqual(event.actor, "superadmin")
        self.assertEqual(event.actor_auth_source, "bootstrap")

    def test_bad_bootstrap_password_never_falls_through_to_cognito(self):
        """A reserved username must not be attempted against the directory."""
        calls = []

        def explode(*args, **kwargs):  # pragma: no cover - must not run
            calls.append(args)
            raise AssertionError("Cognito was contacted for the bootstrap username")

        from authentication.services import auth_service

        original = auth_service._authenticate_cognito
        auth_service._authenticate_cognito = explode
        try:
            response = self.client.post(
                reverse("authentication:login"),
                {"username": "superadmin", "password": "wrong"},
            )
        finally:
            auth_service._authenticate_cognito = original

        self.assertEqual(response.status_code, 401)
        self.assertEqual(calls, [])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_failed_bootstrap_login_is_throttled_like_any_other(self):
        for _ in range(5):
            self.client.post(
                reverse("authentication:login"),
                {"username": "superadmin", "password": "wrong"},
            )

        self.assertEqual(LoginAttempt.objects.filter(successful=False).count(), 5)

        response = self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": PASSWORD},
        )

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)
