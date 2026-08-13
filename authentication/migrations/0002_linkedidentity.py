"""Add LinkedIdentity and backfill it from the existing Cognito mirrors.

No existing ``ScraposUser`` row is modified, renamed or deleted. Each account
that already carries a ``cognito_sub`` gains exactly one ``LinkedIdentity``
describing the identity it was created from, so the new resolution path
recognises returning users on their very next sign-in instead of provisioning a
second account for them.

The provider is inferred from the stored username prefix, which is the only
provider evidence a pre-migration row has. A row whose provider cannot be
determined is recorded as a native Cognito identity keyed on its ``sub`` —
correct for password accounts, and harmless for a federated one because the
``cognito_sub``/``cognito_username`` fallbacks still match it, after which the
next sign-in records the accurate provider row from the token's ``identities``
claim.
"""

from django.db import migrations, models
import django.db.models.deletion


PREFIXES = (
    ("google_", "google"),
    ("facebook_", "facebook"),
    ("signinwithapple_", "apple"),
)


def backfill(apps, schema_editor):
    ScraposUser = apps.get_model("authentication", "ScraposUser")
    LinkedIdentity = apps.get_model("authentication", "LinkedIdentity")

    rows = []
    for user in ScraposUser.objects.exclude(cognito_sub__isnull=True).exclude(cognito_sub=""):
        if user.auth_source == "bootstrap":
            # The emergency administrator is not a directory identity.
            continue

        username = user.username or ""
        lowered = username.lower()
        provider = "cognito"
        subject = user.cognito_sub
        for prefix, candidate in PREFIXES:
            if lowered.startswith(prefix):
                provider = candidate
                subject = username.split("_", 1)[1] or user.cognito_sub
                break

        rows.append(
            LinkedIdentity(
                user_id=user.pk,
                provider=provider,
                provider_subject=subject,
                cognito_username=username,
                cognito_sub=user.cognito_sub,
                email=user.email or "",
                normalized_email=(user.email or "").strip().lower(),
                # Unknown for historical rows. Left False so this row can never
                # be the basis of an email-based link on its own; the next
                # sign-in sets it from the token.
                email_verified=False,
                last_login_at=user.last_login,
            )
        )

    LinkedIdentity.objects.bulk_create(rows, ignore_conflicts=True)


def unbackfill(apps, schema_editor):
    apps.get_model("authentication", "LinkedIdentity").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="LinkedIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("cognito", "Email/password"),
                            ("google", "Google"),
                            ("facebook", "Facebook"),
                            ("apple", "Apple"),
                            ("other", "Other"),
                        ],
                        default="cognito",
                        max_length=30,
                    ),
                ),
                ("provider_subject", models.CharField(max_length=255)),
                ("cognito_username", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("cognito_sub", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("normalized_email", models.CharField(blank=True, db_index=True, default="", max_length=254)),
                ("email_verified", models.BooleanField(default=False)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="linked_identities",
                        to="authentication.scraposuser",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "linked identities",
            },
        ),
        migrations.AddConstraint(
            model_name="linkedidentity",
            constraint=models.UniqueConstraint(
                fields=("provider", "provider_subject"), name="unique_provider_subject"
            ),
        ),
        migrations.AlterField(
            model_name="scraposuser",
            name="cognito_sub",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Cognito subject of the identity this account was first seen through. "
                    "Null for the bootstrap account. Not the resolution key — see LinkedIdentity."
                ),
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(backfill, unbackfill),
    ]
