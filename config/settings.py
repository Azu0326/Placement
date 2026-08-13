import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# The test runner forces DEBUG=False, which would otherwise trip the production
# authentication checks; individual tests supply their own Cognito settings.
TESTING = "test" in sys.argv[1:2]

# Dev fallback only when DEBUG is unset/true locally. Production must inject
# SECRET_KEY from Secrets Manager (see deploy/ecs/web-task-definition.json).
_secret = os.environ.get("SECRET_KEY")
DEBUG = os.environ.get("DEBUG", "True").lower() in {"1", "true", "yes", "on"}
if not _secret:
    if not DEBUG:
        raise RuntimeError("SECRET_KEY must be set when DEBUG is False")
    _secret = "django-insecure-scrapos-frontend-dev-only"
SECRET_KEY = _secret

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


INSTALLED_APPS = [
    # django.contrib.admin is intentionally absent: Scrapos ships its own
    # administration UI under /dashboard/ and the classic Django admin is not
    # the product interface. django.contrib.auth stays for sessions, the
    # password hashers and login plumbing.
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "authentication",
    "dashboard",
    "frontend_demo",
]

MIDDLEWARE = [
    # First: ALB probes by private IP:port, not scrapos.dncouncil.org.
    "config.health.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After AuthenticationMiddleware: both need request.user.
    "authentication.middleware.CognitoSessionRevalidationMiddleware",
    "authentication.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "frontend_demo.context_processors.shell",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Fully environment-driven so the engine can be moved without a code change.
# Production currently runs SQLite on the container's ephemeral disk: sessions,
# the local Cognito user mirror and the audit log therefore reset on each
# deployment. Cognito remains the source of truth for identity, so sign-in is
# unaffected. Point DB_ENGINE/DB_HOST at the shared Postgres instance to make
# the audit log durable — see docs/authentication.md.
DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("DB_NAME", str(BASE_DIR / "db.sqlite3")),
    }
}

if "sqlite" in DATABASES["default"]["ENGINE"]:
    # Several gunicorn workers share one file; without a busy timeout a
    # concurrent session write surfaces as "database is locked".
    DATABASES["default"]["OPTIONS"] = {
        "timeout": 20,
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
    }
else:
    DATABASES["default"].update(
        {
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", ""),
            "PORT": os.environ.get("DB_PORT", ""),
            "CONN_MAX_AGE": _env_int("DB_CONN_MAX_AGE", 60),
        }
    )

AUTH_PASSWORD_VALIDATORS = []

# --- Authentication -------------------------------------------------------
#
#   Browser
#      |
#      v
#   Scrapos Django  ──  /login/          password form (both providers)
#      |               └ /auth/login/    Cognito hosted UI (code flow)
#      |
#      +---- Cognito authentication          (identity lives in the user pool)
#      +---- Bootstrap superadmin            (never present in Cognito)
#      |
#      v
#   Scrapos server-side session ── authorization ── custom dashboard
#
# Cognito passwords are never stored or synchronised locally; the local user
# row exists only to carry Scrapos metadata. See docs/authentication.md.

AUTH_USER_MODEL = "authentication.ScraposUser"

# Credential verification lives in authentication.services.auth_service, not in
# a backend chain, so no second provider can answer for a rejected username.
AUTHENTICATION_BACKENDS = ["authentication.backends.ScraposSessionBackend"]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

COGNITO_REGION = os.environ.get("COGNITO_REGION", os.environ.get("AWS_DEFAULT_REGION", ""))
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.environ.get("COGNITO_CLIENT_SECRET", "")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "")
COGNITO_REDIRECT_URI = os.environ.get("COGNITO_REDIRECT_URI", "")
COGNITO_LOGOUT_REDIRECT_URI = os.environ.get("COGNITO_LOGOUT_REDIRECT_URI", "")

COGNITO_GROUP_ADMIN = os.environ.get("COGNITO_GROUP_ADMIN", "SCRAPOS_ADMIN")
COGNITO_GROUP_EDITOR = os.environ.get("COGNITO_GROUP_EDITOR", "SCRAPOS_EDITOR")
COGNITO_GROUP_VIEWER = os.environ.get("COGNITO_GROUP_VIEWER", "SCRAPOS_VIEWER")

# How often a signed-in Cognito user is re-checked against the directory, so a
# disabled account loses its Scrapos session without waiting for expiry.
SCRAPOS_COGNITO_REVALIDATE_SECONDS = _env_int("SCRAPOS_COGNITO_REVALIDATE_SECONDS", 300)

# Bootstrap superadmin. Only ever a hash — there is no plaintext setting.
SCRAPOS_BOOTSTRAP_ADMIN_ENABLED = _env_bool("SCRAPOS_BOOTSTRAP_ADMIN_ENABLED", True)
SCRAPOS_SUPERADMIN_USERNAME = os.environ.get("SCRAPOS_SUPERADMIN_USERNAME", "")
SCRAPOS_SUPERADMIN_PASSWORD_HASH = os.environ.get("SCRAPOS_SUPERADMIN_PASSWORD_HASH", "")

SCRAPOS_LOGIN_THROTTLE_ENABLED = _env_bool("SCRAPOS_LOGIN_THROTTLE_ENABLED", True)
SCRAPOS_LOGIN_THROTTLE_MAX_PER_USER = _env_int("SCRAPOS_LOGIN_THROTTLE_MAX_PER_USER", 5)
SCRAPOS_LOGIN_THROTTLE_MAX_PER_IP = _env_int("SCRAPOS_LOGIN_THROTTLE_MAX_PER_IP", 20)
SCRAPOS_LOGIN_THROTTLE_WINDOW_MINUTES = _env_int("SCRAPOS_LOGIN_THROTTLE_WINDOW_MINUTES", 15)

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "scrapos_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = _env_int("SESSION_COOKIE_AGE", 8 * 60 * 60)
SESSION_SAVE_EVERY_REQUEST = True
# Lax, not Strict: the Cognito hosted UI redirects back cross-site, and a
# Strict cookie would not be sent on that first navigation.
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "scrapos": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "scrapos",
        },
    },
    "loggers": {
        # Event names only — never credentials, tokens or client secrets.
        "scrapos.auth": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "scrapos.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = _env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", False)
