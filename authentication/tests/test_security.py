"""Security properties of the authentication surface."""

from __future__ import annotations

from unittest import mock

from django.contrib.auth.hashers import make_password
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from authentication import audit
from authentication.models import AuditEvent, LoginAttempt, ScraposUser
from authentication.roles import ROLE_ADMINISTRATOR
from authentication.services.auth_service import BACKEND_PATH
from authentication.services.cognito_service import AuthTokens, CognitoService

from .factories import COGNITO_SETTINGS, install_jwks, signed_id_token

PASSWORD = "bootstrap-password-for-tests"

BOOTSTRAP = {
    "SCRAPOS_BOOTSTRAP_ADMIN_ENABLED": True,
    "SCRAPOS_SUPERADMIN_USERNAME": "superadmin",
    "SCRAPOS_SUPERADMIN_PASSWORD_HASH": make_password(PASSWORD),
}


@override_settings(**COGNITO_SETTINGS, **BOOTSTRAP)
class CsrfTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_login_without_a_csrf_token_is_rejected(self):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": PASSWORD},
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_action_without_a_csrf_token_is_rejected(self):
        user = ScraposUser.objects.create_user(
            username="admin", role=ROLE_ADMINISTRATOR, cognito_sub="sub-admin"
        )
        self.client.force_login(user, backend=BACKEND_PATH)

        response = self.client.post(
            reverse("dashboard:user_action", args=["jane"]),
            {"action": "disable"},
        )

        self.assertEqual(response.status_code, 403)

    def test_login_page_renders_a_csrf_token(self):
        self.assertContains(self.client.get(reverse("authentication:login")), "csrfmiddlewaretoken")


@override_settings(**COGNITO_SETTINGS, **BOOTSTRAP)
class OpenRedirectTests(TestCase):
    def _login_with_next(self, next_value):
        return self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": PASSWORD, "next": next_value},
        )

    def test_external_next_is_discarded(self):
        hostile = [
            "https://evil.example/steal",
            "//evil.example/steal",
            "http://evil.example",
            "https:/\\evil.example",
        ]
        for candidate in hostile:
            with self.subTest(candidate=candidate):
                self.client.logout()
                LoginAttempt.objects.all().delete()
                response = self._login_with_next(candidate)
                self.assertEqual(response["Location"], "/")

    def test_internal_next_is_honoured(self):
        response = self._login_with_next("/dashboard/users/")
        self.assertEqual(response["Location"], "/dashboard/users/")


@override_settings(**COGNITO_SETTINGS, **BOOTSTRAP)
class ThrottlingTests(TestCase):
    def test_repeated_failures_lock_the_username(self):
        for _ in range(5):
            response = self.client.post(
                reverse("authentication:login"),
                {"username": "superadmin", "password": "wrong"},
            )
            self.assertEqual(response.status_code, 401)

        response = self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 429)

    def test_throttling_is_audited(self):
        for _ in range(6):
            self.client.post(
                reverse("authentication:login"),
                {"username": "superadmin", "password": "wrong"},
            )

        self.assertTrue(AuditEvent.objects.filter(action="authentication_throttled").exists())

    def test_a_successful_login_clears_prior_failures(self):
        for _ in range(3):
            self.client.post(
                reverse("authentication:login"),
                {"username": "superadmin", "password": "wrong"},
            )

        self.client.post(
            reverse("authentication:login"),
            {"username": "superadmin", "password": PASSWORD},
        )

        self.assertEqual(
            LoginAttempt.objects.filter(username="superadmin", successful=False).count(), 0
        )


@override_settings(**COGNITO_SETTINGS, **BOOTSTRAP)
class SensitiveDataTests(TestCase):
    def test_secrets_never_appear_in_the_login_page(self):
        response = self.client.get(reverse("authentication:login"))
        body = response.content.decode()

        for secret in [
            COGNITO_SETTINGS["COGNITO_CLIENT_SECRET"],
            COGNITO_SETTINGS["COGNITO_USER_POOL_ID"],
            BOOTSTRAP["SCRAPOS_SUPERADMIN_PASSWORD_HASH"],
            PASSWORD,
        ]:
            self.assertNotIn(secret, body)

    def test_a_submitted_password_is_not_echoed_back(self):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": "someone", "password": "my-secret-password"},
        )

        self.assertNotIn("my-secret-password", response.content.decode())

    def test_dashboard_never_renders_the_client_secret(self):
        user = ScraposUser.objects.create_user(
            username="admin", role=ROLE_ADMINISTRATOR, cognito_sub="sub-admin"
        )
        self.client.force_login(user, backend=BACKEND_PATH)

        with mock.patch.object(CognitoService, "connectivity", return_value=("connected", "ok")), \
             mock.patch.object(CognitoService, "list_users", return_value=[]), \
             mock.patch.object(CognitoService, "list_users_in_group", return_value=[]):
            for path in ["/dashboard/", "/dashboard/settings/", "/dashboard/users/"]:
                with self.subTest(path=path):
                    body = self.client.get(path).content.decode()
                    self.assertNotIn(COGNITO_SETTINGS["COGNITO_CLIENT_SECRET"], body)
                    self.assertNotIn(BOOTSTRAP["SCRAPOS_SUPERADMIN_PASSWORD_HASH"], body)

    def test_audit_metadata_drops_credential_shaped_keys(self):
        audit.record(
            "test_event",
            actor="jane",
            password="hunter2",
            access_token="abc",
            refresh_token="def",
            client_secret="ghi",
            password_hash="jkl",
            role="editor",
        )

        event = AuditEvent.objects.get(action="test_event")
        self.assertEqual(event.metadata, {"role": "editor"})

    def test_malformed_forwarded_ip_does_not_break_auditing(self):
        audit.record("test_event", actor="jane", ip_address="not-an-ip")
        self.assertIsNone(AuditEvent.objects.get(action="test_event").ip_address)


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class SecurityHeaderTests(TestCase):
    def test_security_headers_are_present(self):
        response = self.client.get(reverse("authentication:login"))

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")

    def test_login_page_is_not_cached(self):
        response = self.client.get(reverse("authentication:login"))
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class HostedUiFlowTests(TestCase):
    def setUp(self):
        install_jwks()

    def test_callback_without_matching_state_is_rejected(self):
        response = self.client.get(
            reverse("authentication:oauth_callback"),
            {"code": "abc", "state": "forged"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_state_is_single_use(self):
        start = self.client.get(reverse("authentication:oauth_start"))
        self.assertEqual(start.status_code, 302)
        state = self.client.session["scrapos_oidc_state"]
        nonce = self.client.session["scrapos_oidc_nonce"]

        tokens = AuthTokens(id_token=signed_id_token(nonce=nonce), access_token="a")
        with mock.patch.object(CognitoService, "exchange_code", return_value=tokens):
            first = self.client.get(
                reverse("authentication:oauth_callback"), {"code": "abc", "state": state}
            )
            self.assertEqual(first.status_code, 302)

            second = self.client.get(
                reverse("authentication:oauth_callback"), {"code": "abc", "state": state}
            )

        self.assertEqual(second.status_code, 400)

    def test_authorize_url_uses_the_code_flow_with_pkce(self):
        response = self.client.get(reverse("authentication:oauth_start"))
        location = response["Location"]

        self.assertIn("response_type=code", location)
        self.assertIn("code_challenge_method=S256", location)
        self.assertNotIn("response_type=token", location)


@override_settings(SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class MisconfigurationTests(TestCase):
    def test_missing_cognito_in_production_is_a_startup_error(self):
        from authentication.checks import COGNITO_INCOMPLETE, check_authentication_configuration

        with override_settings(
            DEBUG=False,
            TESTING=False,
            COGNITO_REGION="",
            COGNITO_USER_POOL_ID="",
            COGNITO_CLIENT_ID="",
        ):
            issues = check_authentication_configuration(None)

        self.assertIn(COGNITO_INCOMPLETE, [issue.id for issue in issues])

    def test_plaintext_bootstrap_password_is_a_startup_error(self):
        from authentication.checks import BOOTSTRAP_PLAINTEXT, check_authentication_configuration

        with override_settings(
            **COGNITO_SETTINGS,
            SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=True,
            SCRAPOS_SUPERADMIN_USERNAME="superadmin",
            SCRAPOS_SUPERADMIN_PASSWORD_HASH="plaintext-not-a-hash",
        ):
            issues = check_authentication_configuration(None)

        self.assertIn(BOOTSTRAP_PLAINTEXT, [issue.id for issue in issues])

    def test_a_valid_production_configuration_raises_no_errors(self):
        from authentication.checks import check_authentication_configuration

        with override_settings(**COGNITO_SETTINGS, DEBUG=False, TESTING=False):
            issues = check_authentication_configuration(None)

        self.assertEqual([i for i in issues if i.is_serious()], [])
