"""Cognito password sign-in, token verification and session handling."""

from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from authentication.conf import get_cognito_config
from authentication.exceptions import InvalidToken
from authentication.models import AuditEvent, ScraposUser
from authentication.roles import ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_VIEWER
from authentication.services.cognito_service import AuthTokens, CognitoService
from authentication.tokens import verify_id_token

from .factories import (
    COGNITO_SETTINGS,
    TEST_CLIENT_ID,
    install_jwks,
    signed_id_token,
)


def _tokens(**kwargs) -> AuthTokens:
    return AuthTokens(id_token=signed_id_token(**kwargs), access_token="access", expires_in=3600)


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class TokenVerificationTests(TestCase):
    def setUp(self):
        install_jwks()

    def test_valid_token_is_accepted(self):
        claims = verify_id_token(signed_id_token(), get_cognito_config())
        self.assertEqual(claims["sub"], "sub-1234")

    def test_expired_token_is_rejected(self):
        with self.assertRaises(InvalidToken):
            verify_id_token(signed_id_token(expires_in=-120), get_cognito_config())

    def test_wrong_audience_is_rejected(self):
        with self.assertRaises(InvalidToken):
            verify_id_token(signed_id_token(audience="someone-else"), get_cognito_config())

    def test_wrong_issuer_is_rejected(self):
        with self.assertRaises(InvalidToken):
            verify_id_token(
                signed_id_token(issuer_override="https://evil.example/pool"),
                get_cognito_config(),
            )

    def test_access_token_cannot_establish_a_session(self):
        with self.assertRaises(InvalidToken):
            verify_id_token(signed_id_token(token_use="access"), get_cognito_config())

    def test_unknown_signing_key_is_rejected(self):
        with self.assertRaises(InvalidToken):
            verify_id_token(signed_id_token(kid="rotated-away"), get_cognito_config())

    def test_unsigned_token_is_rejected(self):
        import jwt

        forged = jwt.encode(
            {"sub": "x", "aud": TEST_CLIENT_ID, "token_use": "id"},
            key="",
            algorithm="none",
            headers={"kid": "test-key-1"},
        )
        with self.assertRaises(InvalidToken):
            verify_id_token(forged, get_cognito_config())

    def test_nonce_mismatch_is_rejected(self):
        with self.assertRaises(InvalidToken):
            verify_id_token(
                signed_id_token(nonce="expected"),
                get_cognito_config(),
                nonce="different",
            )


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class CognitoLoginViewTests(TestCase):
    def setUp(self):
        install_jwks()

    def _login(self, tokens, username="jane.doe", password="s3cret"):
        with mock.patch.object(CognitoService, "authenticate", return_value=tokens):
            return self.client.post(
                reverse("authentication:login"),
                {"username": username, "password": password},
            )

    def test_valid_login_creates_a_local_mirror(self):
        response = self._login(_tokens(groups=["SCRAPOS_EDITOR"]))

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        user = ScraposUser.objects.get()
        self.assertEqual(user.username, "jane.doe")
        self.assertEqual(user.cognito_sub, "sub-1234")
        self.assertEqual(user.role, ROLE_EDITOR)
        self.assertEqual(user.auth_source, "cognito")

    def test_no_cognito_password_is_stored(self):
        self._login(_tokens())
        self.assertFalse(ScraposUser.objects.get().has_usable_password())

    def test_group_membership_sets_the_role(self):
        cases = [
            (["SCRAPOS_ADMIN"], ROLE_ADMINISTRATOR),
            (["SCRAPOS_EDITOR"], ROLE_EDITOR),
            (["SCRAPOS_VIEWER"], ROLE_VIEWER),
            ([], ROLE_VIEWER),
            (["DNC_MEMBER"], ROLE_VIEWER),
            (["SCRAPOS_VIEWER", "SCRAPOS_ADMIN"], ROLE_ADMINISTRATOR),
        ]
        for groups, expected in cases:
            with self.subTest(groups=groups):
                ScraposUser.objects.all().delete()
                self.client.logout()
                self._login(_tokens(groups=groups))
                self.assertEqual(ScraposUser.objects.get().role, expected)

    def test_role_is_refreshed_on_each_login(self):
        self._login(_tokens(groups=["SCRAPOS_ADMIN"]))
        self.assertEqual(ScraposUser.objects.get().role, ROLE_ADMINISTRATOR)

        self.client.logout()
        self._login(_tokens(groups=["SCRAPOS_VIEWER"]))
        self.assertEqual(ScraposUser.objects.get().role, ROLE_VIEWER)

    def test_user_is_matched_on_sub_not_email(self):
        self._login(_tokens(username="jane.doe", email="jane@old.example"))
        self.client.logout()
        self._login(_tokens(username="jane.doe", email="jane@new.example"))

        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(ScraposUser.objects.get().email, "jane@new.example")

    def test_invalid_credentials_render_a_generic_message(self):
        from authentication.exceptions import AuthenticationFailed

        with mock.patch.object(CognitoService, "authenticate", side_effect=AuthenticationFailed()):
            response = self.client.post(
                reverse("authentication:login"),
                {"username": "jane.doe", "password": "wrong"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertContains(response, "Invalid username or password.", status_code=401)

    def test_disabled_user_is_indistinguishable_from_a_wrong_password(self):
        from authentication.exceptions import UserDisabled

        with mock.patch.object(CognitoService, "authenticate", side_effect=UserDisabled()):
            response = self.client.post(
                reverse("authentication:login"),
                {"username": "jane.doe", "password": "s3cret"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertContains(response, "Invalid username or password.", status_code=401)
        # The reason must not leak into the page — only "disabled:" utility
        # classes on the submit button may contain the word.
        body = response.content.decode()
        for phrase in ["is disabled", "account is disabled", "user is disabled"]:
            self.assertNotIn(phrase, body.lower())

    def test_cognito_outage_does_not_look_like_a_bad_password(self):
        from authentication.exceptions import CognitoUnavailable

        with mock.patch.object(CognitoService, "authenticate", side_effect=CognitoUnavailable()):
            response = self.client.post(
                reverse("authentication:login"),
                {"username": "jane.doe", "password": "s3cret"},
            )

        self.assertEqual(response.status_code, 503)

    def test_missing_cognito_configuration_refuses_rather_than_allowing(self):
        with override_settings(COGNITO_USER_POOL_ID="", COGNITO_CLIENT_ID=""):
            response = self.client.post(
                reverse("authentication:login"),
                {"username": "jane.doe", "password": "s3cret"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_rotates_the_session_key(self):
        self.client.get(reverse("authentication:login"))
        self.client.session["planted"] = "value"
        self.client.session.save()
        before = self.client.session.session_key

        self._login(_tokens())

        self.assertNotEqual(self.client.session.session_key, before)

    def test_successful_login_is_audited_without_credentials(self):
        self._login(_tokens())

        event = AuditEvent.objects.get(action="authentication_success")
        self.assertEqual(event.actor, "jane.doe")
        serialised = str(event.metadata)
        self.assertNotIn("s3cret", serialised)
        self.assertNotIn("password", serialised)


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class LogoutTests(TestCase):
    def setUp(self):
        install_jwks()
        with mock.patch.object(CognitoService, "authenticate", return_value=_tokens()):
            self.client.post(
                reverse("authentication:login"),
                {"username": "jane.doe", "password": "s3cret"},
            )

    def test_logout_destroys_the_session(self):
        self.assertIn("_auth_user_id", self.client.session)

        self.client.post(reverse("authentication:logout"))

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_rejects_get(self):
        response = self.client.get(reverse("authentication:logout"))

        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_is_audited(self):
        self.client.post(reverse("authentication:logout"))
        self.assertTrue(AuditEvent.objects.filter(action="logout", actor="jane.doe").exists())
