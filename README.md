# Scrapos

DNC Content Platform. Django application at https://scrapos.dncouncil.org.

## Local development

```bash
cp .env.example .env
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py hash_bootstrap_password --generate
```

Put the generated hash in `SCRAPOS_SUPERADMIN_PASSWORD_HASH`, then:

```bash
python manage.py runserver
```

Sign in with the bootstrap account. Cognito can stay blank while `DEBUG=True`.

```bash
python manage.py test authentication dashboard scraper --noinput
python tools/smoke_routes.py
```

## Scraper

See [docs/scraper.md](docs/scraper.md) for the New Scraper Job wizard, worker
setup, Study Australia example, exports and security limits.

Authentication is documented in [docs/authentication.md](docs/authentication.md).
