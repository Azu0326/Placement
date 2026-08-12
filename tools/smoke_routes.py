"""Smoke-test Scrapos routes (used in CI and locally)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import django
from django.conf import settings
from django.test import Client


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "ci-smoke-secret")
    os.environ.setdefault("DEBUG", "False")
    os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")
    os.environ.setdefault("DB_ENGINE", "django.db.backends.sqlite3")
    os.environ.setdefault("DB_NAME", "/tmp/scrapos-smoke.sqlite3")

    django.setup()

    from django.core.management import call_command

    call_command("migrate", "--noinput", verbosity=0)

    client = Client()
    paths = [
        "/healthz",
        "/",
        "/scraper/jobs/",
        "/studio/content/",
        "/poster/schedule/",
        "/repository/assets/",
        "/integrations/",
        "/design/states/",
    ]
    failed = 0
    for path in paths:
        response = client.get(path)
        ok = response.status_code == 200
        mark = "OK" if ok else "FAIL"
        print(f"{mark} {path} -> {response.status_code}")
        if not ok:
            failed += 1

    if failed:
        print(f"{failed} route(s) failed", file=sys.stderr)
        return 1
    print(f"All {len(paths)} routes OK (settings={settings.DJANGO_SETTINGS_MODULE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
