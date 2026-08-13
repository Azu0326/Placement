"""Social sign-in through the Cognito hosted UI, and identity resolution.

The rule under test throughout: one person is one ``ScraposUser``, whichever of
their linked providers they arrive through. Two shapes of "same person" are
covered, because the pool produces both:

* **Cognito-linked** — ``AdminLinkProviderForUser`` has attached the providers
  to one Cognito record, so every sign-in carries the same ``sub`` and an
  ``identities`` claim listing all of them;
* **not linked in Cognito** — each provider is its own Cognito record with its
  own ``sub``, and the only server-derived evidence that they are one person is
  a verified email. This is the case the member portal's ``LinkedIdentity``
  layer exists to handle, and the case the old ``sub``-only lookup got wrong.

No test reaches AWS: the token endpoint is mocked and the ID tokens are really
signed against a local key pair, so validation runs for real.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from authentication.identity import (
    PROVIDER_APPLE,
    PROVIDER_COGNITO,
    PROVIDER_FACEBOOK,
    PROVIDER_GOOGLE,
    email_is_verified,
    infer_provider,
    linkable_identities,
    provider_subject_from,
)
from authentication.models import AuditEvent, LinkedIdentity, ScraposUser
from authentication.oidc import SESSION_NONCE, SESSION_STATE
from authentication.roles import AUTH_SOURCE_BOOTSTRAP, ROLE_EDITOR
from authentication.services.cognito_service import AuthTokens, CognitoService

from .factories import COGNITO_SETTINGS, install_jwks, signed_id_token, social_id_token

#: The three Cognito records of one person who has NOT been linked pool-side.
UNLINKED = {
    PROVIDER_GOOGLE: {"subject": "110248495", "sub": "sub-google"},
    PROVIDER_FACEBOOK: {"subject": "987654321", "sub": "sub-facebook"},
    PROVIDER_APPLE: {"subject": "001122.abcdef", "sub": "sub-apple"},
}

#: The same person after ``AdminLinkProviderForUser``: one record, one sub.
LINKED_SUB = "sub-canonical"


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class SocialSignInTestCase(TestCase):
    """Drives the real ``/auth/social/<provider>/`` → ``/auth/callback/`` pair."""

    email = "jane.doe@example.org"

    def setUp(self):
        install_jwks()

    # -- helpers ----------------------------------------------------------

    def start(self, provider: str = PROVIDER_GOOGLE, **query):
        url = (
            reverse("authentication:oauth_social", args=[provider])
            if provider
            else reverse("authentication:oauth_start")
        )
        return self.client.get(url, query)

    def callback(self, build_token, *, provider: str = PROVIDER_GOOGLE, state=None, **query):
        """Start the flow, then complete it with the token ``build_token`` mints."""
        self.start(provider)
        session = self.client.session
        id_token = build_token(nonce=session[SESSION_NONCE])
        tokens = AuthTokens(id_token=id_token, access_token="access-token", expires_in=3600)

        params = {"code": "auth-code", "state": session[SESSION_STATE] if state is None else state}
        params.update(query)
        with mock.patch.object(CognitoService, "exchange_code", return_value=tokens):
            return self.client.get(reverse("authentication:oauth_callback"), params)

    def sign_in_linked(self, provider: str, *, email=None, groups=None):
        """A provider of a Cognito-linked record: one sub, all three identities."""
        others = [(name, cfg["subject"]) for name, cfg in UNLINKED.items() if name != provider]
        return self.callback(
            lambda nonce: social_id_token(
                provider,
                subject=UNLINKED[provider]["subject"],
                sub=LINKED_SUB,
                email=email or self.email,
                also_linked=others,
                groups=groups,
                nonce=nonce,
            ),
            provider=provider,
        )

    def sign_in_unlinked(self, provider: str, *, email=None, email_verified=True):
        """A provider that is its own Cognito record — nothing linked pool-side."""
        return self.callback(
            lambda nonce: social_id_token(
                provider,
                subject=UNLINKED[provider]["subject"],
                sub=UNLINKED[provider]["sub"],
                email=email or self.email,
                email_verified=email_verified,
                nonce=nonce,
            ),
            provider=provider,
        )

    def sign_in_password(self, *, email=None, sub="sub-native", username="jane.doe"):
        """Native email/password sign-in, for the mixed-provider cases."""
        return self.callback(
            lambda nonce: signed_id_token(
                sub=sub, username=username, email=email or self.email, nonce=nonce,
            ),
            provider="",
        )

    def logout(self):
        self.client.post(reverse("authentication:logout"))

    def assertSignedIn(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        return int(self.client.session["_auth_user_id"])


class AuthorizeUrlTests(SocialSignInTestCase):
    def test_provider_route_sends_the_browser_straight_to_that_provider(self):
        cases = {
            PROVIDER_GOOGLE: "Google",
            PROVIDER_FACEBOOK: "Facebook",
            PROVIDER_APPLE: "SignInWithApple",
        }
        for provider, cognito_name in cases.items():
            with self.subTest(provider=provider):
                response = self.start(provider)
                self.assertEqual(response.status_code, 302)
                self.assertIn(f"identity_provider={cognito_name}", response["Location"])
                self.assertIn("code_challenge_method=S256", response["Location"])
                self.assertIn("response_type=code", response["Location"])

    def test_generic_route_keeps_the_hosted_form_for_password_accounts(self):
        response = self.start("")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("identity_provider", response["Location"])

    def test_unknown_provider_is_refused_without_starting_a_flow(self):
        response = self.client.get(reverse("authentication:oauth_social", args=["myspace"]))

        self.assertRedirects(response, reverse("authentication:login"), fetch_redirect_response=False)
        self.assertNotIn(SESSION_STATE, self.client.session)

    def test_login_page_offers_every_configured_provider(self):
        response = self.client.get(reverse("authentication:login"))
        for provider in (PROVIDER_GOOGLE, PROVIDER_FACEBOOK, PROVIDER_APPLE):
            self.assertContains(response, reverse("authentication:oauth_social", args=[provider]))


class FirstSocialLoginTests(SocialSignInTestCase):
    def test_google_login_for_a_new_user(self):
        user_id = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))

        user = ScraposUser.objects.get(pk=user_id)
        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(user.email, self.email)
        self.assertEqual(user.auth_source, "cognito")
        self.assertFalse(user.has_usable_password())
        identity = user.linked_identities.get()
        self.assertEqual(identity.provider, PROVIDER_GOOGLE)
        self.assertEqual(identity.provider_subject, UNLINKED[PROVIDER_GOOGLE]["subject"])

    def test_facebook_login_for_a_new_user(self):
        user_id = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_FACEBOOK))

        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(
            ScraposUser.objects.get(pk=user_id).linked_identities.get().provider,
            PROVIDER_FACEBOOK,
        )

    def test_apple_login_for_a_new_user(self):
        user_id = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_APPLE))

        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(
            ScraposUser.objects.get(pk=user_id).linked_identities.get().provider,
            PROVIDER_APPLE,
        )

    def test_the_username_is_not_the_provider_record_name(self):
        self.sign_in_unlinked(PROVIDER_GOOGLE)

        user = ScraposUser.objects.get()
        self.assertNotIn("Google_", user.username)
        self.assertEqual(user.username, "jane.doe")

    def test_role_comes_from_the_signed_groups_claim(self):
        self.sign_in_linked(PROVIDER_GOOGLE, groups=["SCRAPOS_EDITOR"])
        self.assertEqual(ScraposUser.objects.get().role, ROLE_EDITOR)


class ReturningSocialLoginTests(SocialSignInTestCase):
    def test_google_login_for_an_existing_user(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))
        self.logout()
        second = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))

        self.assertEqual(first, second)
        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(LinkedIdentity.objects.count(), 1)

    def test_facebook_login_for_an_existing_user(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_FACEBOOK))
        self.logout()
        second = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_FACEBOOK))

        self.assertEqual(first, second)
        self.assertEqual(ScraposUser.objects.count(), 1)

    def test_apple_login_for_an_existing_user(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_APPLE))
        self.logout()
        second = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_APPLE))

        self.assertEqual(first, second)
        self.assertEqual(ScraposUser.objects.count(), 1)

    def test_last_login_is_recorded_on_the_linked_identity(self):
        self.sign_in_unlinked(PROVIDER_GOOGLE)
        self.assertIsNotNone(LinkedIdentity.objects.get().last_login_at)


class ProviderSwitchingTests(SocialSignInTestCase):
    """The regression this whole change exists for."""

    def _switch(self, first: str, second: str, sign_in):
        first_id = self.assertSignedIn(sign_in(first))
        self.logout()
        second_id = self.assertSignedIn(sign_in(second))

        self.assertEqual(
            first_id,
            second_id,
            f"{first} and {second} resolved to different Scrapos users",
        )
        self.assertEqual(ScraposUser.objects.count(), 1)
        return first_id

    # -- linked in Cognito (one record, one sub, identities claim) --------

    def test_linked_account_google_then_facebook(self):
        self._switch(PROVIDER_GOOGLE, PROVIDER_FACEBOOK, self.sign_in_linked)

    def test_linked_account_google_then_apple(self):
        self._switch(PROVIDER_GOOGLE, PROVIDER_APPLE, self.sign_in_linked)

    def test_linked_account_facebook_then_apple(self):
        self._switch(PROVIDER_FACEBOOK, PROVIDER_APPLE, self.sign_in_linked)

    def test_all_linked_identities_are_recorded_on_the_first_sign_in(self):
        self.sign_in_linked(PROVIDER_GOOGLE)

        providers = set(
            ScraposUser.objects.get().linked_identities.values_list("provider", flat=True)
        )
        self.assertEqual(providers, {PROVIDER_GOOGLE, PROVIDER_FACEBOOK, PROVIDER_APPLE})

    # -- separate Cognito records, same verified email --------------------

    def test_unlinked_records_google_then_facebook(self):
        self._switch(PROVIDER_GOOGLE, PROVIDER_FACEBOOK, self.sign_in_unlinked)

    def test_unlinked_records_google_then_apple(self):
        self._switch(PROVIDER_GOOGLE, PROVIDER_APPLE, self.sign_in_unlinked)

    def test_unlinked_records_facebook_then_apple(self):
        self._switch(PROVIDER_FACEBOOK, PROVIDER_APPLE, self.sign_in_unlinked)

    def test_all_three_providers_in_sequence_stay_one_user(self):
        seen = set()
        for provider in (PROVIDER_GOOGLE, PROVIDER_FACEBOOK, PROVIDER_APPLE):
            seen.add(self.assertSignedIn(self.sign_in_unlinked(provider)))
            self.logout()

        self.assertEqual(len(seen), 1)
        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(LinkedIdentity.objects.count(), 3)

    def test_password_account_then_social_stays_one_user(self):
        native = self.assertSignedIn(self.sign_in_password())
        self.logout()
        social = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))

        self.assertEqual(native, social)
        self.assertEqual(ScraposUser.objects.count(), 1)

    def test_social_then_password_stays_one_user(self):
        social = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_APPLE))
        self.logout()
        native = self.assertSignedIn(self.sign_in_password())

        self.assertEqual(social, native)
        self.assertEqual(ScraposUser.objects.count(), 1)

    def test_linking_an_existing_account_is_audited(self):
        self.sign_in_unlinked(PROVIDER_GOOGLE)
        self.logout()
        self.sign_in_unlinked(PROVIDER_FACEBOOK)

        event = AuditEvent.objects.filter(action="identity_linked").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.metadata["provider"], PROVIDER_FACEBOOK)
        # The address itself is never stored on the event.
        self.assertNotIn(self.email, str(event.metadata))


class SeparatePeopleTests(SocialSignInTestCase):
    def test_different_people_get_different_accounts(self):
        self.sign_in_unlinked(PROVIDER_GOOGLE, email="jane.doe@example.org")
        self.logout()
        self.callback(
            lambda nonce: social_id_token(
                PROVIDER_FACEBOOK,
                subject="55550000",
                sub="sub-other-person",
                email="john.roe@example.org",
                nonce=nonce,
            ),
            provider=PROVIDER_FACEBOOK,
        )

        self.assertEqual(ScraposUser.objects.count(), 2)

    def test_an_unverified_email_never_joins_an_existing_account(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))
        self.logout()
        # An identity provider that asserts the address without verifying it
        # must not be able to take over the account behind it.
        second = self.assertSignedIn(
            self.sign_in_unlinked(PROVIDER_APPLE, email_verified=False)
        )

        self.assertNotEqual(first, second)
        self.assertEqual(ScraposUser.objects.count(), 2)

    def test_google_without_an_email_verified_claim_is_treated_as_unverified(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_FACEBOOK))
        self.logout()
        second = self.assertSignedIn(
            self.callback(
                lambda nonce: social_id_token(
                    PROVIDER_GOOGLE,
                    subject=UNLINKED[PROVIDER_GOOGLE]["subject"],
                    sub=UNLINKED[PROVIDER_GOOGLE]["sub"],
                    email=self.email,
                    email_verified=None,
                    nonce=nonce,
                ),
                provider=PROVIDER_GOOGLE,
            )
        )

        self.assertNotEqual(first, second)

    def test_a_social_login_cannot_take_over_the_bootstrap_account(self):
        boot = ScraposUser.objects.create(
            username="superadmin",
            email=self.email,
            auth_source=AUTH_SOURCE_BOOTSTRAP,
        )

        user_id = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))

        self.assertNotEqual(user_id, boot.pk)
        self.assertEqual(ScraposUser.objects.filter(auth_source=AUTH_SOURCE_BOOTSTRAP).count(), 1)


class DuplicateAccountTests(SocialSignInTestCase):
    def test_two_accounts_on_one_verified_email_are_flagged_not_merged(self):
        older = ScraposUser.objects.create(
            username="jane.doe", email=self.email, cognito_sub="sub-old-a",
        )
        newer = ScraposUser.objects.create(
            username="jane.doe.2", email=self.email, cognito_sub="sub-old-b",
        )

        user_id = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))

        # Deterministic choice, both rows preserved, nothing merged.
        self.assertEqual(user_id, older.pk)
        self.assertTrue(ScraposUser.objects.filter(pk=newer.pk).exists())
        self.assertEqual(ScraposUser.objects.count(), 2)
        self.assertTrue(AuditEvent.objects.filter(action="identity_duplicate_detected").exists())
        # No link is persisted against a guess.
        self.assertEqual(LinkedIdentity.objects.count(), 0)


class CallbackSecurityTests(SocialSignInTestCase):
    def test_invalid_oauth_state_is_rejected(self):
        response = self.callback(
            lambda nonce: social_id_token(
                PROVIDER_GOOGLE, subject="1", sub="s", nonce=nonce,
            ),
            state="tampered-state",
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(ScraposUser.objects.count(), 0)

    def test_a_replayed_callback_cannot_succeed_twice(self):
        self.start(PROVIDER_GOOGLE)
        session = self.client.session
        state, nonce = session[SESSION_STATE], session[SESSION_NONCE]
        tokens = AuthTokens(
            id_token=social_id_token(
                PROVIDER_GOOGLE,
                subject=UNLINKED[PROVIDER_GOOGLE]["subject"],
                sub=UNLINKED[PROVIDER_GOOGLE]["sub"],
                nonce=nonce,
            ),
            access_token="access-token",
        )
        url = reverse("authentication:oauth_callback")
        with mock.patch.object(CognitoService, "exchange_code", return_value=tokens):
            first = self.client.get(url, {"code": "auth-code", "state": state})
            self.logout()
            replay = self.client.get(url, {"code": "auth-code", "state": state})

        self.assertEqual(first.status_code, 302)
        self.assertEqual(replay.status_code, 400)

    def test_an_expired_token_is_rejected(self):
        response = self.callback(
            lambda nonce: social_id_token(
                PROVIDER_GOOGLE, subject="1", sub="s", expires_in=-120, nonce=nonce,
            )
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(ScraposUser.objects.count(), 0)

    def test_a_token_for_another_client_is_rejected(self):
        response = self.callback(
            lambda nonce: social_id_token(
                PROVIDER_GOOGLE, subject="1", sub="s", audience="another-app", nonce=nonce,
            )
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ScraposUser.objects.count(), 0)

    def test_a_token_from_another_pool_is_rejected(self):
        response = self.callback(
            lambda nonce: social_id_token(
                PROVIDER_GOOGLE,
                subject="1",
                sub="s",
                issuer_override="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_evil",
                nonce=nonce,
            )
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ScraposUser.objects.count(), 0)

    def test_a_token_minted_for_a_different_request_is_rejected(self):
        response = self.callback(
            lambda nonce: social_id_token(
                PROVIDER_GOOGLE, subject="1", sub="s", nonce="not-our-nonce",
            )
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ScraposUser.objects.count(), 0)

    def test_a_provider_error_returns_a_safe_generic_message(self):
        self.start(PROVIDER_GOOGLE)
        response = self.client.get(
            reverse("authentication:oauth_callback"),
            {"error": "access_denied", "error_description": "user cancelled"},
        )

        self.assertEqual(response.status_code, 401)
        body = response.content.decode()
        self.assertIn("Invalid username or password.", body)
        self.assertNotIn("access_denied", body)
        self.assertNotIn("user cancelled", body)

    def test_a_failed_token_exchange_does_not_create_an_account(self):
        from authentication.exceptions import AuthenticationFailed

        self.start(PROVIDER_GOOGLE)
        session = self.client.session
        with mock.patch.object(
            CognitoService, "exchange_code", side_effect=AuthenticationFailed()
        ):
            response = self.client.get(
                reverse("authentication:oauth_callback"),
                {"code": "auth-code", "state": session[SESSION_STATE]},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ScraposUser.objects.count(), 0)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_no_token_material_reaches_the_audit_trail(self):
        self.sign_in_unlinked(PROVIDER_GOOGLE)

        serialised = " ".join(str(event.metadata) for event in AuditEvent.objects.all())
        for secret in ("eyJ", "access-token", "auth-code", "test-client-secret"):
            self.assertNotIn(secret, serialised)


class SessionAndRedirectTests(SocialSignInTestCase):
    def test_the_callback_lands_on_the_default_page(self):
        response = self.sign_in_unlinked(PROVIDER_GOOGLE)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_a_same_site_next_is_honoured(self):
        self.start(PROVIDER_GOOGLE, next="/jobs/")
        session = self.client.session
        tokens = AuthTokens(
            id_token=social_id_token(
                PROVIDER_GOOGLE,
                subject=UNLINKED[PROVIDER_GOOGLE]["subject"],
                sub=UNLINKED[PROVIDER_GOOGLE]["sub"],
                nonce=session[SESSION_NONCE],
            ),
            access_token="access-token",
        )
        with mock.patch.object(CognitoService, "exchange_code", return_value=tokens):
            response = self.client.get(
                reverse("authentication:oauth_callback"),
                {"code": "auth-code", "state": session[SESSION_STATE]},
            )

        self.assertRedirects(response, "/jobs/", fetch_redirect_response=False)

    def test_an_offsite_next_is_discarded(self):
        self.start(PROVIDER_GOOGLE, next="https://evil.example/steal")
        session = self.client.session
        tokens = AuthTokens(
            id_token=social_id_token(
                PROVIDER_GOOGLE,
                subject=UNLINKED[PROVIDER_GOOGLE]["subject"],
                sub=UNLINKED[PROVIDER_GOOGLE]["sub"],
                nonce=session[SESSION_NONCE],
            ),
            access_token="access-token",
        )
        with mock.patch.object(CognitoService, "exchange_code", return_value=tokens):
            response = self.client.get(
                reverse("authentication:oauth_callback"),
                {"code": "auth-code", "state": session[SESSION_STATE]},
            )

        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_social_sign_in_rotates_the_session_key(self):
        self.client.get(reverse("authentication:login"))
        session = self.client.session
        session["planted"] = "value"
        session.save()
        before = session.session_key

        self.sign_in_unlinked(PROVIDER_GOOGLE)

        self.assertNotEqual(self.client.session.session_key, before)

    def test_logout_then_sign_in_again_reuses_the_same_account(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))

        response = self.client.post(reverse("authentication:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        # Cognito's own session is ended too, so the hosted UI cannot sign the
        # user straight back in.
        self.assertIn("logout", response["Location"])

        second = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_FACEBOOK))
        self.assertEqual(first, second)
        self.assertEqual(ScraposUser.objects.count(), 1)


class ClaimReadingTests(TestCase):
    """Unit coverage for the claim interpretation the resolver depends on."""

    def _claims(self, **overrides):
        claims = {"sub": "s", "cognito:username": "jane.doe", "email": "jane@example.org"}
        claims.update(overrides)
        return claims

    def test_provider_is_read_from_the_identities_claim(self):
        claims = self._claims(
            **{
                "cognito:username": "Google_110248495",
                "identities": [
                    {"userId": "110248495", "providerName": "Google", "primary": True},
                ],
            }
        )
        self.assertEqual(infer_provider(claims), PROVIDER_GOOGLE)
        self.assertEqual(provider_subject_from(claims, PROVIDER_GOOGLE), "110248495")

    def test_provider_falls_back_to_the_username_prefix(self):
        cases = {
            "Google_1": PROVIDER_GOOGLE,
            "Facebook_2": PROVIDER_FACEBOOK,
            "SignInWithApple_3": PROVIDER_APPLE,
            "jane.doe": PROVIDER_COGNITO,
        }
        for username, expected in cases.items():
            with self.subTest(username=username):
                claims = self._claims(**{"cognito:username": username})
                self.assertEqual(infer_provider(claims), expected)

    def test_identities_sent_as_a_json_string_are_understood(self):
        claims = self._claims(
            **{
                "cognito:username": "Facebook_987",
                "identities": '[{"userId": "987", "providerName": "Facebook", "primary": "true"}]',
            }
        )
        self.assertEqual(infer_provider(claims), PROVIDER_FACEBOOK)

    def test_a_linked_record_yields_every_identity(self):
        claims = self._claims(
            **{
                "cognito:username": "jane.doe",
                "identities": [
                    {"userId": "g1", "providerName": "Google", "primary": False},
                    {"userId": "f1", "providerName": "Facebook", "primary": False},
                ],
            }
        )
        pairs = linkable_identities(claims)
        self.assertIn((PROVIDER_GOOGLE, "g1"), pairs)
        self.assertIn((PROVIDER_FACEBOOK, "f1"), pairs)
        # The native record it is linked into is kept too.
        self.assertIn((PROVIDER_COGNITO, "s"), pairs)

    def test_email_verification_defaults_per_provider(self):
        absent = self._claims()
        self.assertTrue(email_is_verified(absent, PROVIDER_COGNITO))
        self.assertTrue(email_is_verified(absent, PROVIDER_FACEBOOK))
        self.assertFalse(email_is_verified(absent, PROVIDER_GOOGLE))
        self.assertFalse(email_is_verified(absent, PROVIDER_APPLE))

    def test_an_explicit_claim_wins_in_both_directions(self):
        self.assertTrue(email_is_verified(self._claims(email_verified=True), PROVIDER_APPLE))
        self.assertTrue(email_is_verified(self._claims(email_verified="true"), PROVIDER_GOOGLE))
        self.assertFalse(email_is_verified(self._claims(email_verified=False), PROVIDER_FACEBOOK))
        self.assertFalse(email_is_verified(self._claims(email_verified="false"), PROVIDER_COGNITO))


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class ApplePrivateRelayTests(SocialSignInTestCase):
    relay = "abc123xyz@privaterelay.appleid.com"

    def test_a_relay_address_only_ever_matches_itself(self):
        first = self.assertSignedIn(self.sign_in_unlinked(PROVIDER_GOOGLE))
        self.logout()
        second = self.assertSignedIn(
            self.sign_in_unlinked(PROVIDER_APPLE, email=self.relay)
        )

        self.assertNotEqual(first, second)
        self.assertEqual(ScraposUser.objects.count(), 2)

    def test_a_relay_address_does_not_overwrite_a_real_one(self):
        self.sign_in_unlinked(PROVIDER_GOOGLE)
        self.logout()
        # Same Cognito record (linked pool-side), signing in through Apple,
        # which hands back the relay alias instead of the real address.
        self.callback(
            lambda nonce: social_id_token(
                PROVIDER_APPLE,
                subject=UNLINKED[PROVIDER_APPLE]["subject"],
                sub=UNLINKED[PROVIDER_GOOGLE]["sub"],
                email=self.relay,
                also_linked=[(PROVIDER_GOOGLE, UNLINKED[PROVIDER_GOOGLE]["subject"])],
                nonce=nonce,
            ),
            provider=PROVIDER_APPLE,
        )

        self.assertEqual(ScraposUser.objects.count(), 1)
        self.assertEqual(ScraposUser.objects.get().email, self.email)
