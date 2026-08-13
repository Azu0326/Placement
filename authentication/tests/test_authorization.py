"""Server-side authorisation across roles."""

from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.urls import reverse

from authentication.models import AuditEvent, ScraposUser
from authentication.roles import (
    AUTH_SOURCE_BOOTSTRAP,
    ROLE_ADMINISTRATOR,
    ROLE_EDITOR,
    ROLE_SUPERADMIN,
    ROLE_VIEWER,
)
from authentication.services.auth_service import BACKEND_PATH

from .factories import COGNITO_SETTINGS

ADMIN_URLS = [
    "/dashboard/",
    "/dashboard/users/",
    "/dashboard/groups/",
    "/dashboard/audit/",
    "/dashboard/settings/",
    "/dashboard/users/new/",
]


def make_user(username, role, auth_source="cognito", **extra):
    return ScraposUser.objects.create_user(
        username=username,
        role=role,
        auth_source=auth_source,
        cognito_sub=f"sub-{username}" if auth_source == "cognito" else None,
        **extra,
    )


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class UnauthenticatedAccessTests(TestCase):
    def test_application_pages_redirect_to_login(self):
        for path in ["/", "/scraper/jobs/", "/studio/content/"] + ADMIN_URLS:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response["Location"])

    def test_the_login_page_itself_is_public(self):
        self.assertEqual(self.client.get("/login/").status_code, 200)

    def test_health_check_stays_public(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_redirect_preserves_the_requested_page(self):
        response = self.client.get("/dashboard/users/")
        self.assertIn("next=%2Fdashboard%2Fusers%2F", response["Location"])


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class ViewerAuthorizationTests(TestCase):
    def setUp(self):
        self.user = make_user("viewer", ROLE_VIEWER)
        self.client.force_login(self.user, backend=BACKEND_PATH)

    def test_viewer_can_reach_content_pages(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_viewer_cannot_reach_any_admin_route(self):
        for path in ADMIN_URLS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_viewer_cannot_post_a_user_action(self):
        response = self.client.post(
            reverse("dashboard:user_action", args=["someone"]),
            {"action": "disable"},
        )
        self.assertEqual(response.status_code, 403)

    def test_denial_is_audited(self):
        self.client.get("/dashboard/users/")

        event = AuditEvent.objects.get(action="permission_denied")
        self.assertEqual(event.actor, "viewer")
        self.assertEqual(event.metadata["required_role"], ROLE_ADMINISTRATOR)

    def test_admin_navigation_is_not_rendered(self):
        response = self.client.get("/")
        self.assertNotContains(response, 'href="/dashboard/users/"')


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class EditorAuthorizationTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("editor", ROLE_EDITOR), backend=BACKEND_PATH)

    def test_editor_cannot_administer_users(self):
        self.assertEqual(self.client.get("/dashboard/users/").status_code, 403)

    def test_editor_cannot_change_a_role(self):
        response = self.client.post(
            reverse("dashboard:user_action", args=["viewer"]),
            {"action": "set_role", "role": ROLE_ADMINISTRATOR},
        )
        self.assertEqual(response.status_code, 403)

    def test_editor_can_reach_content(self):
        self.assertEqual(self.client.get("/studio/content/").status_code, 200)


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class AdministratorAuthorizationTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user("admin", ROLE_ADMINISTRATOR), backend=BACKEND_PATH)

    def test_administrator_reaches_the_dashboard(self):
        for path in ADMIN_URLS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_admin_navigation_is_rendered(self):
        self.assertContains(self.client.get("/"), 'href="/dashboard/users/"')


@override_settings(
    **COGNITO_SETTINGS,
    SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=True,
    SCRAPOS_SUPERADMIN_USERNAME="superadmin",
    SCRAPOS_SUPERADMIN_PASSWORD_HASH=make_password("pw"),
)
class BootstrapAuthorizationTests(TestCase):
    def setUp(self):
        self.user = make_user("superadmin", ROLE_SUPERADMIN, auth_source=AUTH_SOURCE_BOOTSTRAP)
        self.client.force_login(self.user, backend=BACKEND_PATH)

    def test_bootstrap_superadmin_reaches_every_admin_route(self):
        for path in ADMIN_URLS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_bootstrap_row_is_labelled_in_the_user_list(self):
        self.assertContains(self.client.get("/dashboard/users/"), "Bootstrap Superadmin")

    def test_bootstrap_account_cannot_be_acted_on_from_the_ui(self):
        response = self.client.post(
            reverse("dashboard:user_action", args=["superadmin"]),
            {"action": "disable"},
            follow=True,
        )

        self.assertContains(response, "managed through its secret")
        self.assertTrue(ScraposUser.objects.get(username="superadmin").is_active)

    def test_bootstrap_username_cannot_be_created_in_cognito(self):
        response = self.client.post(
            reverse("dashboard:user_new"),
            {
                "username": "superadmin",
                "email": "super@example.org",
                "role": ROLE_VIEWER,
            },
        )

        self.assertContains(response, "reserved")


@override_settings(**COGNITO_SETTINGS, SCRAPOS_BOOTSTRAP_ADMIN_ENABLED=False)
class DeactivatedUserTests(TestCase):
    def test_a_deactivated_user_becomes_anonymous(self):
        user = make_user("jane", ROLE_ADMINISTRATOR)
        self.client.force_login(user, backend=BACKEND_PATH)
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)

        ScraposUser.objects.filter(pk=user.pk).update(is_active=False)

        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
