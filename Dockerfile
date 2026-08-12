# Scrapos production image.
#
# Built for linux/arm64: outvier-ecs-cluster-production hosts are t4g.medium
# (Graviton). An amd64 image will pull and then fail to start.

FROM python:3.12-slim AS base

FROM base AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM base AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

RUN SECRET_KEY=build-time-only-not-used-at-runtime \
    DEBUG=False \
    ALLOWED_HOSTS=localhost \
    DB_ENGINE=django.db.backends.sqlite3 \
    DB_NAME=/tmp/build.sqlite3 \
    python manage.py collectstatic --noinput \
    && python manage.py migrate --noinput \
    && chown -R appuser:appuser /app/staticfiles

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:8000/healthz || exit 1

# Ephemeral SQLite is migrated at boot so Django contrib tables exist.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers ${GUNICORN_WORKERS:-2} \
    --timeout ${GUNICORN_TIMEOUT:-60} \
    --access-logfile - \
    --error-logfile -"]
