"""Smoke-test Scrapos routes (used in CI and locally).

Scrapos is closed by default: every application page redirects an anonymous
visitor to /login/. The checks below therefore assert the *expected* status for
each route rather than a blanket 200, and then sign in with a throwaway
bootstrap credential to confirm the authenticated pages still render.

No AWS call is made: the bootstrap provider is entirely local, which is one of
the reasons it exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import django
from django.test import Client

SMOKE_USERNAME = "smoke-superadmin"
SMOKE_PASSWORD = "smoke-only-not-a-real-credential"

ANONYMOUS_ROUTES = [
    ("/healthz", 200),
    ("/login/", 200),
    ("/", 302),
    ("/dashboard/", 302),
    ("/scraper/jobs/", 302),
    # Closed by default: an unknown path redirects to sign-in rather than
    # confirming to an anonymous visitor whether it exists.
    ("/admin/", 302),
]

#: Routes that must not exist even for an administrator. The classic Django
#: admin is not installed and must never become the product interface.
AUTHENTICATED_NOT_FOUND = ["/admin/", "/admin/login/"]

AUTHENTICATED_ROUTES = [
    "/",
    "/scraper/jobs/",
    "/studio/content/",
    "/poster/schedule/",
    "/repository/assets/",
    "/integrations/",
    "/design/states/",
    "/dashboard/",
    "/dashboard/users/",
    "/dashboard/groups/",
    "/dashboard/audit/",
    "/dashboard/settings/",
]


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "ci-smoke-secret")
    os.environ.setdefault("DEBUG", "False")
    # Force testserver: CI may set ALLOWED_HOSTS without it, and setdefault
    # would then leave Django Test Client requests returning 400 DisallowedHost.
    hosts = {h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()}
    hosts.update({"testserver", "localhost", "127.0.0.1"})
    os.environ["ALLOWED_HOSTS"] = ",".join(sorted(hosts))
    os.environ.setdefault("DB_ENGINE", "django.db.backends.sqlite3")
    os.environ.setdefault("DB_NAME", "/tmp/scrapos-smoke.sqlite3")

    django.setup()

    from django.contrib.auth.hashers import make_password
    from django.core.management import call_command
    from django.test import override_settings

    call_command("migrate", "--noinput", verbosity=0)

    failed = 0

    for path, expected in ANONYMOUS_ROUTES:
        status = Client().get(path).status_code
        good = status == expected
        print(f"{'OK' if good else 'FAIL'} anon {path} -> {status} (expected {expected})")
        if not good:
            failed += 1

    smoke_settings = {
        "SCRAPOS_BOOTSTRAP_ADMIN_ENABLED": True,
        "SCRAPOS_SUPERADMIN_USERNAME": SMOKE_USERNAME,
        "SCRAPOS_SUPERADMIN_PASSWORD_HASH": make_password(SMOKE_PASSWORD),
        # Deliberately unconfigured: the smoke test must not call AWS, and this
        # also proves the dashboard degrades to its "configuration error" state
        # instead of failing, which is what a Cognito outage looks like.
        "COGNITO_USER_POOL_ID": "",
        "COGNITO_CLIENT_ID": "",
    }

    with override_settings(**smoke_settings):
        client = Client()
        login = client.post(
            "/login/", {"username": SMOKE_USERNAME, "password": SMOKE_PASSWORD}
        )
        if login.status_code != 302:
            print(f"FAIL bootstrap sign-in -> {login.status_code} (expected 302)", file=sys.stderr)
            return 1
        print("OK  bootstrap sign-in -> 302")

        for path in AUTHENTICATED_ROUTES:
            status = client.get(path).status_code
            good = status == 200
            print(f"{'OK' if good else 'FAIL'} auth {path} -> {status}")
            if not good:
                failed += 1

        for path in AUTHENTICATED_NOT_FOUND:
            status = client.get(path).status_code
            good = status == 404
            print(f"{'OK' if good else 'FAIL'} auth {path} -> {status} (expected 404)")
            if not good:
                failed += 1

        logout = client.post("/logout/")
        if logout.status_code != 302 or "_auth_user_id" in client.session:
            print("FAIL logout did not clear the session", file=sys.stderr)
            failed += 1
        else:
            print("OK  logout cleared the session")

    if failed:
        print(f"{failed} check(s) failed", file=sys.stderr)
        return 1

    total = len(ANONYMOUS_ROUTES) + len(AUTHENTICATED_ROUTES) + len(AUTHENTICATED_NOT_FOUND)
    print(f"All {total} route checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
