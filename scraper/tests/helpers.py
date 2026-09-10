from pathlib import Path

from authentication.models import ScraposUser
from authentication.roles import ROLE_EDITOR, ROLE_VIEWER
from scraper.models import ScrapeField, ScrapeJob, ScrapeRun, VariableParameter
from scraper.services.jobs import create_draft, replace_fields, replace_variables
from scraper.services.snapshots import snapshot_job

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_user(username: str, role: str = ROLE_EDITOR) -> ScraposUser:
    return ScraposUser.objects.create_user(username=username, role=role, cognito_sub=f"sub-{username}")


def make_job(owner, **overrides) -> ScrapeJob:
    job = create_draft(owner, name=overrides.pop("name", "Test job"))
    for key, value in overrides.items():
        setattr(job, key, value)
    job.save()
    return job


def configure_listing_job(job: ScrapeJob) -> ScrapeJob:
    job.start_url = "https://search.studyaustralia.gov.au/scholarships?page=1"
    job.url_template = "https://search.studyaustralia.gov.au/scholarships?page={{page}}"
    job.result_selector = ".scholarship-list-card"
    job.detail_link_selector = "h3 a"
    job.follow_detail_pages = True
    job.unique_field_name = "detail_url"
    job.maximum_pages = 3
    job.pagination_settings = {
        "mode": "query_parameter",
        "variable": "page",
        "parameter": "page",
        "start": 1,
        "increment": 1,
        "maximum_pages": 3,
        "url_template": job.url_template,
        "stop_conditions": ["no_result_items", "no_new_detail_urls", "repeated_page", "maximum_pages_reached"],
    }
    job.save()
    replace_variables(
        job,
        [
            {
                "name": "page",
                "label": "Page",
                "source_type": "counter",
                "data_type": "integer",
                "required": True,
                "configuration": {"start_value": 1, "increment": 1, "maximum_value": 100},
            }
        ],
    )
    replace_fields(
        job,
        [
            {
                "name": "scholarship_name",
                "label": "Scholarship Name",
                "scope": "result_item",
                "selector": "h3 a",
                "extraction_method": "text_content",
                "data_type": "text",
                "required": True,
                "transformations": ["trim"],
            },
            {
                "name": "detail_url",
                "label": "Detail URL",
                "scope": "result_item",
                "selector": "h3 a",
                "extraction_method": "attribute",
                "attribute_name": "href",
                "data_type": "url",
                "required": True,
                "unique": True,
                "transformations": ["trim", "resolve_absolute_url"],
            },
            {
                "name": "description",
                "label": "Description",
                "scope": "detail_page",
                "selector": ".content-body p.mb-2:last-of-type",
                "extraction_method": "text_content",
                "data_type": "text",
                "transformations": ["trim"],
            },
            {"name": "source_page", "label": "Source Page", "scope": "system", "data_type": "integer"},
            {"name": "source_url", "label": "Source URL", "scope": "system", "data_type": "url"},
            {"name": "scraped_at", "label": "Scraped At", "scope": "system", "data_type": "datetime"},
        ],
    )
    return job


def queued_run(job: ScrapeJob, user) -> ScrapeRun:
    return ScrapeRun.objects.create(job=job, snapshot=snapshot_job(job), requested_by=user, job_version=job.version)
