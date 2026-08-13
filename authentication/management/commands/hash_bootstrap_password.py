"""Generate a bootstrap superadmin password hash.

Rotation is a secret update, never a code change:

    python manage.py hash_bootstrap_password --generate

prints a fresh password and its Django hash. Put the *hash* in the
``outvier-scrapos-django-production`` secret under
``bootstrap_admin_password_hash`` and redeploy. The plaintext is shown once and
is not written anywhere.
"""

from __future__ import annotations

import secrets
import string

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

# Ambiguous glyphs removed so the password survives being read aloud or
# retyped from a terminal.
ALPHABET = (
    "".join(c for c in string.ascii_letters if c not in "lIO")
    + "".join(c for c in string.digits if c not in "01")
    + "!@#%^*-_=+?"
)


def generate_password(length: int = 28) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


class Command(BaseCommand):
    help = "Generate a Django password hash for the bootstrap superadmin."

    def add_arguments(self, parser):
        parser.add_argument(
            "--generate",
            action="store_true",
            help="Generate a strong random password and hash it.",
        )
        parser.add_argument(
            "--password",
            help="Hash this password instead of generating one. Avoid in shared shells.",
        )
        parser.add_argument("--length", type=int, default=28)
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Print only the hash, for piping into a secret update.",
        )

    def handle(self, *args, **options):
        password = options.get("password")
        generated = False

        if not password:
            if not options["generate"]:
                raise CommandError("Pass --generate, or --password to hash an existing value.")
            password = generate_password(options["length"])
            generated = True

        password_hash = make_password(password)

        if options["quiet"]:
            self.stdout.write(password_hash)
            return

        if generated:
            self.stdout.write(self.style.WARNING("Generated password (shown once, store it now):"))
            self.stdout.write(password)
            self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("SCRAPOS_SUPERADMIN_PASSWORD_HASH:"))
        self.stdout.write(password_hash)
        self.stdout.write("")
        self.stdout.write(
            "Store the hash in Secrets Manager, never in git:\n"
            "  aws secretsmanager put-secret-value \\\n"
            "    --secret-id outvier-scrapos-django-production \\\n"
            "    --secret-string '{\"secret_key\":\"…\",\"bootstrap_admin_username\":\"superadmin\","
            "\"bootstrap_admin_password_hash\":\"<hash>\"}'\n"
            "then redeploy the ECS service."
        )
