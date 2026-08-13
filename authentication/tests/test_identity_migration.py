"""Migration 0002 against rows that already exist in production.

The upgrade must be invisible to people who already have an account: nothing
renamed, nothing deleted, and a ``LinkedIdentity`` for every directory account
so the new resolution path recognises them on their next sign-in instead of
provisioning a second one.
"""

from __future__ import annotations

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

MIGRATE_FROM = ("authentication", "0001_initial")
MIGRATE_TO = ("authentication", "0002_linkedidentity")


class LinkedIdentityBackfillTests(TransactionTestCase):
    def _migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        executor.loader.build_graph()
        return executor.loader.project_state([target]).apps

    def setUp(self):
        old_apps = self._migrate(MIGRATE_FROM)
        user_model = old_apps.get_model("authentication", "ScraposUser")

        # A native account, two federated ones named after their Cognito
        # record, and the bootstrap administrator.
        user_model.objects.create(
            username="jane.doe", cognito_sub="sub-native",
            email="Jane.Doe@Example.org", auth_source="cognito", password="!",
        )
        user_model.objects.create(
            username="Google_110248495", cognito_sub="sub-google",
            email="jane.doe@example.org", auth_source="cognito", password="!",
        )
        user_model.objects.create(
            username="SignInWithApple_001122.ab", cognito_sub="sub-apple",
            email="", auth_source="cognito", password="!",
        )
        user_model.objects.create(
            username="superadmin", cognito_sub=None, email="",
            auth_source="bootstrap", password="!",
        )

        self.apps = self._migrate(MIGRATE_TO)

    def tearDown(self):
        # Leave the schema at the latest migration for the rest of the suite.
        self._migrate(MIGRATE_TO)

    def test_no_existing_account_is_renamed_or_removed(self):
        user_model = self.apps.get_model("authentication", "ScraposUser")

        self.assertEqual(
            sorted(user_model.objects.values_list("username", flat=True)),
            ["Google_110248495", "SignInWithApple_001122.ab", "jane.doe", "superadmin"],
        )

    def test_each_directory_account_gains_one_identity(self):
        rows = {
            row.cognito_sub: row
            for row in self.apps.get_model("authentication", "LinkedIdentity").objects.all()
        }

        # The bootstrap administrator is not a directory identity.
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows["sub-native"].provider, "cognito")
        self.assertEqual(rows["sub-native"].provider_subject, "sub-native")
        self.assertEqual(rows["sub-google"].provider, "google")
        self.assertEqual(rows["sub-apple"].provider, "apple")

    def test_the_provider_subject_is_taken_from_the_record_name(self):
        rows = {
            row.cognito_sub: row
            for row in self.apps.get_model("authentication", "LinkedIdentity").objects.all()
        }

        self.assertEqual(rows["sub-google"].provider_subject, "110248495")
        self.assertEqual(rows["sub-apple"].provider_subject, "001122.ab")

    def test_emails_are_normalised_and_never_assumed_verified(self):
        rows = self.apps.get_model("authentication", "LinkedIdentity").objects.all()

        by_sub = {row.cognito_sub: row for row in rows}
        self.assertEqual(by_sub["sub-native"].normalized_email, "jane.doe@example.org")
        # Historical rows carry no verification evidence, so they must never be
        # the basis of an email-based link on their own.
        self.assertFalse(any(row.email_verified for row in rows))
