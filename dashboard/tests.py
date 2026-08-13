"""Administration dashboard behaviour, with Cognito mocked."""

from __future__ import annotations

from unittest import mock

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.urls import reverse

from authentication.models import AuditEvent, ScraposUser
from authentication.roles import ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_VIEWER
from authentication.services.auth_service import BACKEND_PATH
from authentication.services.cognito_service import CognitoService, CognitoUser
from authentication.tests.factories import COGNITO_SETTINGS

DIRECTORY = [
    CognitoUser(
        username="jane.doe",
        sub="sub-1",
        email="jane@example.org",
        name="Jane Doe",
        enabled=True,
        status="CONFIRMED",
    ),
    CognitoUser(
        username="sam.smith",
        sub="sub-2",
        email="sam@example.org",
        name="Sam Smith",
        enabled=False,
        status="CONFIRMED",
    ),
]


def directory_user(username, **kwargs):
    for user in DIRECTORY:
        if user.username == username:
            return user
    return CognitoUser(username=username, sub=f"sub-{username}", enabled=True, status="CONFIRMED")


def group_members(group, **kwargs):
    return {
        "SCRAPOS_ADMIN": ["jane.doe", "other.admin"],
        "SCRAPOS_EDITOR": ["sam.smith"],
        "SCRAPOS_VIEWER": [],
    }.get(group, [])


class DashboardTestCase(TestCase):
    """Signs in an administrator and stubs the directory."""

    def setUp(self):
        self.admin = ScraposUser.objects.create_user(
            username="admin.user", role=ROLE_ADMINISTRATOR, cognito_sub="sub-admin"
        )
        self.client.force_login(self.admin, backend=BACKEND_PATH)

        patches = [
            mock.patch.object(CognitoService, "list_users", return_value=DIRECTORY),
            mock.patch.object(CognitoService, "list_users_in_group", side_effect=group_members),
            mock.patch.object(CognitoService, "connectivity", return_value=("connected", "ok")),
            mock.patch.object(CognitoService, "list_groups", return_value=[]),
            # Actions redirect back to the detail page, which reads the user.
            mock.patch.object(CognitoService, "get_user", side_effect=directory_user),
            mock.patch.object(CognitoService, "groups_for_user", return_value=[]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class DashboardHomeTests(DashboardTestCase):
    def test_metrics_count_the_directory(self):
        response = self.client.get(reverse("dashboard:home"))
        metrics = response.context["metrics"]

        self.assertEqual(metrics["total_users"], 2)
        self.assertEqual(metrics["active_users"], 1)
        self.assertEqual(metrics["disabled_users"], 1)
        self.assertEqual(metrics["administrators"], 1)

    def test_cognito_status_widget_reports_connected(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.context["cognito_status_label"], "Connected")

    def test_status_widget_degrades_without_breaking_the_page(self):
        with mock.patch.object(
            CognitoService, "list_users", side_effect=_permission_denied()
        ), mock.patch.object(
            CognitoService, "connectivity", return_value=("permission_error", "no permission")
        ):
            response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cognito_status_label"], "AWS Permission Error")

    def test_classic_django_admin_is_not_routed(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class UserListTests(DashboardTestCase):
    def test_directory_users_are_listed(self):
        response = self.client.get(reverse("dashboard:users"))
        usernames = [row.username for row in response.context["rows"]]
        self.assertEqual(usernames, ["jane.doe", "sam.smith"])

    def test_status_filter(self):
        response = self.client.get(reverse("dashboard:users"), {"status": "disabled"})
        self.assertEqual([r.username for r in response.context["rows"]], ["sam.smith"])

    def test_role_filter(self):
        response = self.client.get(reverse("dashboard:users"), {"role": ROLE_ADMINISTRATOR})
        self.assertEqual([r.username for r in response.context["rows"]], ["jane.doe"])

    def test_source_filter(self):
        response = self.client.get(reverse("dashboard:users"), {"source": "bootstrap"})
        self.assertEqual(response.context["rows"], [])

    def test_search_is_passed_to_cognito(self):
        with mock.patch.object(CognitoService, "list_users", return_value=[]) as listed:
            self.client.get(reverse("dashboard:users"), {"q": "jane"})
        self.assertEqual(listed.call_args.kwargs["search"], "jane")


@override_settings(
    **COGNITO_SETTINGS,
    SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=True,
    SCRAPOS_SUPERADMIN_USERNAME="superadmin",
    SCRAPOS_SUPERADMIN_PASSWORD_HASH=make_password("pw"),
)
class BootstrapVisibilityTests(DashboardTestCase):
    def test_bootstrap_row_is_listed_and_labelled(self):
        response = self.client.get(reverse("dashboard:users"))
        rows = response.context["rows"]

        self.assertTrue(rows[0].is_bootstrap)
        self.assertEqual(rows[0].source_label, "Bootstrap Superadmin")
        self.assertContains(response, "Managed via secret")

    def test_bootstrap_row_has_no_manage_link(self):
        response = self.client.get(reverse("dashboard:users"))
        self.assertNotContains(response, 'href="/dashboard/users/superadmin/"')

    def test_bootstrap_detail_page_explains_it_is_not_in_cognito(self):
        response = self.client.get(reverse("dashboard:user_detail", args=["superadmin"]))
        self.assertContains(response, "not stored in Cognito")


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class UserActionTests(DashboardTestCase):
    def test_actions_reject_get(self):
        response = self.client.get(reverse("dashboard:user_action", args=["sam.smith"]))
        self.assertEqual(response.status_code, 405)

    def test_disable_calls_cognito_and_audits(self):
        with mock.patch.object(CognitoService, "disable_user") as disable:
            self.client.post(
                reverse("dashboard:user_action", args=["other.admin"]),
                {"action": "disable"},
            )

        disable.assert_called_once_with("other.admin")
        self.assertTrue(AuditEvent.objects.filter(action="user_disabled", target="other.admin").exists())

    def test_enable_calls_cognito_and_audits(self):
        with mock.patch.object(CognitoService, "enable_user") as enable:
            self.client.post(
                reverse("dashboard:user_action", args=["sam.smith"]),
                {"action": "enable"},
            )

        enable.assert_called_once_with("sam.smith")
        self.assertTrue(AuditEvent.objects.filter(action="user_enabled").exists())

    def test_role_change_moves_group_membership(self):
        with mock.patch.object(CognitoService, "add_user_to_group") as add, \
             mock.patch.object(CognitoService, "remove_user_from_group") as remove:
            self.client.post(
                reverse("dashboard:user_action", args=["sam.smith"]),
                {"action": "set_role", "role": ROLE_EDITOR},
            )

        add.assert_called_once_with("sam.smith", "SCRAPOS_EDITOR")
        removed = {call.args[1] for call in remove.call_args_list}
        self.assertEqual(removed, {"SCRAPOS_ADMIN", "SCRAPOS_VIEWER"})

    def test_invalid_role_is_refused(self):
        with mock.patch.object(CognitoService, "add_user_to_group") as add:
            self.client.post(
                reverse("dashboard:user_action", args=["sam.smith"]),
                {"action": "set_role", "role": "superadmin"},
            )
        add.assert_not_called()

    def test_administrator_cannot_disable_themselves(self):
        with mock.patch.object(CognitoService, "disable_user") as disable:
            response = self.client.post(
                reverse("dashboard:user_action", args=["admin.user"]),
                {"action": "disable"},
                follow=True,
            )

        disable.assert_not_called()
        self.assertContains(response, "cannot disable your own account")

    def test_last_administrator_cannot_be_demoted(self):
        with mock.patch.object(CognitoService, "list_users_in_group", return_value=["jane.doe"]), \
             mock.patch.object(CognitoService, "add_user_to_group") as add:
            response = self.client.post(
                reverse("dashboard:user_action", args=["jane.doe"]),
                {"action": "set_role", "role": ROLE_VIEWER},
                follow=True,
            )

        add.assert_not_called()
        self.assertContains(response, "last administrator")

    def test_password_reset_is_delegated_to_cognito(self):
        with mock.patch.object(CognitoService, "reset_password") as reset:
            self.client.post(
                reverse("dashboard:user_action", args=["jane.doe"]),
                {"action": "reset_password"},
            )

        reset.assert_called_once_with("jane.doe")
        self.assertTrue(AuditEvent.objects.filter(action="password_reset_initiated").exists())

    def test_aws_failure_becomes_a_safe_message(self):
        with mock.patch.object(CognitoService, "disable_user", side_effect=_permission_denied()):
            response = self.client.post(
                reverse("dashboard:user_action", args=["other.admin"]),
                {"action": "disable"},
                follow=True,
            )

        self.assertContains(response, "not permitted to perform")


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class UserCreateTests(DashboardTestCase):
    def test_invite_creates_the_user_and_assigns_the_group(self):
        created = CognitoUser(username="new.person", email="new@example.org")
        with mock.patch.object(CognitoService, "create_user", return_value=created) as create, \
             mock.patch.object(CognitoService, "add_user_to_group") as add:
            response = self.client.post(
                reverse("dashboard:user_new"),
                {
                    "username": "new.person",
                    "email": "new@example.org",
                    "display_name": "New Person",
                    "role": ROLE_EDITOR,
                },
            )

        create.assert_called_once()
        add.assert_called_once_with("new.person", "SCRAPOS_EDITOR")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AuditEvent.objects.filter(action="user_created").exists())

    def test_missing_fields_are_reported(self):
        response = self.client.post(reverse("dashboard:user_new"), {"username": "", "email": ""})
        self.assertContains(response, "A username is required.")


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class AuditViewTests(DashboardTestCase):
    def test_events_are_listed_and_filterable(self):
        from authentication import audit

        audit.record(audit.LOGIN_SUCCESS, actor="jane.doe", actor_auth_source="cognito")
        audit.record(audit.USER_DISABLED, actor="admin.user", target="sam.smith")

        response = self.client.get(reverse("dashboard:audit"), {"action": audit.USER_DISABLED})
        actions = [event.action for event in response.context["events"]]

        self.assertEqual(actions, [audit.USER_DISABLED])


def _permission_denied():
    from authentication.exceptions import CognitoPermissionDenied

    return CognitoPermissionDenied()
