"""CognitoService: AWS error translation and administrative calls.

Every test drives a fake boto3 client. Nothing here reaches AWS.
"""

from __future__ import annotations

from django.test import TestCase, override_settings

from authentication.conf import get_cognito_config
from authentication.exceptions import (
    AuthenticationFailed,
    ChallengeRequired,
    CognitoNotConfigured,
    CognitoOperationFailed,
    CognitoPermissionDenied,
    CognitoUnavailable,
    PasswordResetRequired,
    TooManyAttempts,
    UserDisabled,
)
from authentication.services.cognito_service import CognitoService

from .factories import COGNITO_SETTINGS, FakeCognitoClient, client_error


def service(**responses) -> CognitoService:
    return CognitoService(get_cognito_config(), client=FakeCognitoClient(**responses))


@override_settings(**COGNITO_SETTINGS)
class ErrorTranslationTests(TestCase):
    def test_aws_errors_map_to_application_errors(self):
        cases = [
            ("NotAuthorizedException", "Incorrect username or password.", AuthenticationFailed),
            ("NotAuthorizedException", "User is disabled.", UserDisabled),
            ("NotAuthorizedException", "Password attempts exceeded", TooManyAttempts),
            ("UserNotFoundException", "", AuthenticationFailed),
            ("PasswordResetRequiredException", "", PasswordResetRequired),
            ("TooManyRequestsException", "", TooManyAttempts),
            ("AccessDeniedException", "", CognitoPermissionDenied),
            ("InternalErrorException", "", CognitoUnavailable),
            ("ResourceNotFoundException", "", CognitoNotConfigured),
            ("UsernameExistsException", "", CognitoOperationFailed),
        ]
        for code, message, expected in cases:
            with self.subTest(code=code, message=message):
                svc = service(admin_initiate_auth=client_error(code, message))
                with self.assertRaises(expected):
                    svc.authenticate("jane.doe", "pw")

    def test_aws_error_text_never_reaches_the_user_message(self):
        svc = service(
            admin_initiate_auth=client_error(
                "NotAuthorizedException", "Incorrect username or password."
            )
        )
        with self.assertRaises(AuthenticationFailed) as ctx:
            svc.authenticate("jane.doe", "pw")

        self.assertEqual(str(ctx.exception), "Invalid username or password.")

    def test_unknown_error_codes_degrade_to_unavailable(self):
        svc = service(admin_initiate_auth=client_error("SomethingBrandNewException"))
        with self.assertRaises(CognitoUnavailable):
            svc.authenticate("jane.doe", "pw")


@override_settings(**COGNITO_SETTINGS)
class AuthenticateTests(TestCase):
    def test_admin_flow_and_secret_hash_are_used(self):
        client = FakeCognitoClient(
            admin_initiate_auth={"AuthenticationResult": {"IdToken": "t", "ExpiresIn": 3600}}
        )
        CognitoService(get_cognito_config(), client=client).authenticate("jane.doe", "pw")

        operation, kwargs = client.calls[0]
        self.assertEqual(operation, "admin_initiate_auth")
        self.assertEqual(kwargs["AuthFlow"], "ADMIN_USER_PASSWORD_AUTH")
        self.assertIn("SECRET_HASH", kwargs["AuthParameters"])

    def test_a_challenge_does_not_count_as_a_successful_sign_in(self):
        svc = service(admin_initiate_auth={"ChallengeName": "NEW_PASSWORD_REQUIRED"})
        with self.assertRaises(ChallengeRequired):
            svc.authenticate("jane.doe", "pw")

    def test_missing_configuration_raises_before_any_call(self):
        with override_settings(COGNITO_USER_POOL_ID=""):
            with self.assertRaises(CognitoNotConfigured):
                CognitoService().authenticate("jane.doe", "pw")


@override_settings(**COGNITO_SETTINGS)
class DirectoryTests(TestCase):
    def test_list_users_flattens_attributes(self):
        svc = service(
            list_users={
                "Users": [
                    {
                        "Username": "jane.doe",
                        "Enabled": True,
                        "UserStatus": "CONFIRMED",
                        "Attributes": [
                            {"Name": "sub", "Value": "sub-1"},
                            {"Name": "email", "Value": "jane@example.org"},
                            {"Name": "name", "Value": "Jane Doe"},
                        ],
                    }
                ]
            }
        )

        users = svc.list_users()

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0].email, "jane@example.org")
        self.assertEqual(users[0].display_name, "Jane Doe")

    def test_search_becomes_a_prefix_filter(self):
        client = FakeCognitoClient(list_users={"Users": []})
        CognitoService(get_cognito_config(), client=client).list_users(search="jane")

        self.assertEqual(client.calls[0][1]["Filter"], 'email ^= "jane"')

    def test_create_user_never_sets_a_password(self):
        client = FakeCognitoClient(admin_create_user={"User": {"Username": "jane.doe"}})
        CognitoService(get_cognito_config(), client=client).create_user(
            username="jane.doe", email="jane@example.org"
        )

        operation, kwargs = client.calls[0]
        self.assertEqual(operation, "admin_create_user")
        self.assertNotIn("TemporaryPassword", kwargs)
        self.assertNotIn("Password", kwargs)

    def test_enable_disable_and_group_calls_are_scoped_to_the_pool(self):
        client = FakeCognitoClient()
        svc = CognitoService(get_cognito_config(), client=client)

        svc.enable_user("jane.doe")
        svc.disable_user("jane.doe")
        svc.add_user_to_group("jane.doe", "SCRAPOS_EDITOR")
        svc.remove_user_from_group("jane.doe", "SCRAPOS_VIEWER")
        svc.reset_password("jane.doe")

        self.assertEqual(
            [call[0] for call in client.calls],
            [
                "admin_enable_user",
                "admin_disable_user",
                "admin_add_user_to_group",
                "admin_remove_user_from_group",
                "admin_reset_user_password",
            ],
        )
        for _, kwargs in client.calls:
            self.assertEqual(kwargs["UserPoolId"], get_cognito_config().user_pool_id)

    def test_missing_iam_permission_surfaces_as_permission_denied(self):
        svc = service(list_groups=client_error("AccessDeniedException", operation="ListGroups"))
        with self.assertRaises(CognitoPermissionDenied):
            svc.list_groups()


@override_settings(**COGNITO_SETTINGS)
class ConnectivityTests(TestCase):
    def test_reachable_directory_reports_connected(self):
        state, _ = service(list_groups={"Groups": []}).connectivity()
        self.assertEqual(state, "connected")

    def test_failures_are_reported_without_raising(self):
        cases = [
            (client_error("AccessDeniedException"), "permission_error"),
            (client_error("ResourceNotFoundException"), "configuration_error"),
            (client_error("InternalErrorException"), "unavailable"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                state, _ = service(list_groups=error).connectivity()
                self.assertEqual(state, expected)

    def test_unconfigured_cognito_reports_configuration_error(self):
        with override_settings(COGNITO_CLIENT_ID=""):
            state, _ = CognitoService().connectivity()
        self.assertEqual(state, "configuration_error")
