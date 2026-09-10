# Scrapos scraper

Authenticated users configure reusable scraper jobs, run them in the background,
inspect progress and export records as CSV or SQLite.

The extraction engine is website-agnostic. Selectors, variables and pagination
rules are stored on each job. The Study Australia scholarships site is only a
documented acceptance example.

## Architecture

```text
Browser
  └ Django views / JSON APIs
       ├ scraper.services.jobs          draft + wizard persistence
       ├ scraper.services.fetcher       HTTP, optional Playwright
       ├ scraper.services.orchestrator  listing → details → persist
       └ scraper.services.exporters     CSV / SQLite
            │
            └ database-backed queue (no Redis / Celery)
```

Production is a single ECS web task (`deploy/ecs/web-task-definition.json`
explicitly has no Redis or Celery). Runs are claimed with a status update and
executed on a daemon thread inside the web process. `manage.py runscraper`
is available if you later add a dedicated worker task.

User-facing run status stays in the product vocabulary:
`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, plus `PAUSED` and `CANCELLED`.

## Local setup

```bash
cp .env.example .env
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py hash_bootstrap_password --generate
# put the hash in SCRAPOS_SUPERADMIN_PASSWORD_HASH
python manage.py runserver
```

Optional browser rendering (Auto/Browser modes):

```bash
python -m pip install playwright
python -m playwright install chromium
```

Run queued jobs in a second terminal if you disable the inline worker:

```bash
python manage.py runscraper --loop
```

## Environment

See `.env.example`. Caps:

| Variable | Default | Purpose |
|---|---|---|
| `SCRAPER_MAX_PAGES` | 100 | Platform page cap |
| `SCRAPER_MAX_RECORDS` | 5000 | Platform record cap |
| `SCRAPER_MAX_RUN_SECONDS` | 900 | Hard runtime limit |
| `SCRAPER_MAX_RESPONSE_BYTES` | 2000000 | Response size limit |
| `SCRAPER_DEFAULT_DELAY_SECONDS` | 0.5 | Delay between requests |
| `SCRAPER_EXPORT_DIRECTORY` | `var/exports` | Export files (not web-reachable) |
| `SCRAPER_EXPORT_RETENTION_HOURS` | 72 | When exports expire |
| `SCRAPER_INLINE_WORKER` | true | Poll/execute inside the web process |
| `SCRAPER_BROWSER_ENABLED` | true | Allow Playwright fallback |
| `SCRAPER_MAX_CONCURRENCY` | 2 | Detail-page request cap |
| `SCRAPER_BROWSER_CONCURRENCY` | 1 | Concurrent browser pages |
| `SCRAPER_DEFAULT_TIMEOUT_SECONDS` | 20 | Fetch timeout |
| `SCRAPER_DEFAULT_USER_AGENT` | ScrapOS/1.0 | Default User-Agent |
| `SCRAPER_TEST_RATE_LIMIT` | 20 | Test Page requests per window |
| `SCRAPER_RUN_RATE_LIMIT` | 10 | Run starts per window |
| `SCRAPER_WORKER_POLL_SECONDS` | 2 | Inline worker poll interval |

`CELERY_BROKER_URL` is not used. Do not add Redis unless the deployment
architecture changes.

## Creating a job

1. Sign in and open **Scraper → Jobs**.
2. **New scraper job** creates a draft and opens the wizard.
3. Steps: Basic Information → Source and Request → Variable Parameters →
   Result Selection → Detail Page Fields → Pagination → Execution Settings →
   Test and Preview → Review and Save.
4. Drafts persist when you move between steps.
5. A job cannot become Active until validation passes.

Configuration can be entered **manually** or imported from one **Configuration CSV**.
Both write the same variables, result selection and fields. Merge is the default
import mode and never deletes omitted manual rows. Replace requires an explicit
confirmation checkbox. Use **Export configuration** for the job definition and
**Export scraped results CSV/SQLite** for run output. Placeholder selectors
containing `REPLACE_WITH_VERIFIED` warn in preview and block a run until they
are replaced.

Variables use `{{name}}` in URL templates. HTML variables support text,
attributes and transforms from a fixed registry — never user Python or JS.

## Study Australia example

```bash
python manage.py seed_study_australia_job --username superadmin
```

Expected configuration:

- Start URL: `https://search.studyaustralia.gov.au/scholarships?page=1`
- Template: `https://search.studyaustralia.gov.au/scholarships?page={{page}}`
- Counter variable `page` starting at 1
- Result selector: `.scholarship-list-card`
- Detail link: `h3 a[href]`
- Unique field: `detail_url`

The listing is JavaScript-rendered. Auto mode tries HTTP first and falls back
to Playwright when installed. If the live site blocks automated access, use
the HTML fixtures under `scraper/fixtures/html/`.

## Exports

CSV and SQLite are generated in `SCRAPER_EXPORT_DIRECTORY/<run-id>/` and
downloaded through an authorised endpoint. Filesystem paths are never shown.
CSV values that start with `= + - @` are prefixed to prevent formula injection.
SQLite files include `results`, `export_metadata`, `job_configuration` and
`field_definitions` and must pass `PRAGMA integrity_check`.

## Tests

```bash
python manage.py test authentication dashboard scraper --noinput
python tools/smoke_routes.py
```

## Security limits

- SSRF: only http/https; no localhost, private ranges, metadata hosts, or
  embedded credentials; redirects are re-validated.
- HTML previews are sanitized; scraped scripts are never executed.
- Test Page and Run creation are rate-limited.
- The scraper does not bypass CAPTCHAs, logins or bot protection.

## Production

The web container already runs `migrate` at boot. Export files live on the
container disk and disappear when the task is replaced — the same ephemeral
SQLite limitation documented in `docs/authentication.md`. Point
`SCRAPER_EXPORT_DIRECTORY` at durable storage if exports must survive
redeploys. A durable Postgres database is recommended before relying on
scrape history as evidence.
