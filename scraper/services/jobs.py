"""Create and update scraper jobs from wizard payloads."""

from __future__ import annotations

from django.db import transaction
from django.utils.text import slugify

from scraper.constants import JOB_STATUS_ACTIVE, JOB_STATUS_DRAFT, ORIGIN_MANUAL
from scraper.models import ScrapeField, ScrapeJob, VariableParameter

from .config import normalize_field, normalize_variable
from .ssrf import RequestPolicyError, validate_url
from .url_template import infer_page_template
from .validation import JobValidationError, field_name_from_label, validate_job_payload


def unique_slug(owner, name: str, *, exclude_id=None) -> str:
    base = slugify(name)[:200] or "job"
    slug = base
    index = 2
    qs = ScrapeJob.objects.filter(owner=owner)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug


def unique_name(owner, name: str, *, exclude_id=None) -> str:
    candidate = name.strip()
    index = 2
    qs = ScrapeJob.objects.filter(owner=owner)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    while qs.filter(name=candidate).exists():
        candidate = f"{name.strip()} ({index})"
        index += 1
    return candidate


@transaction.atomic
def create_draft(owner, *, name: str = "Untitled scraper") -> ScrapeJob:
    job = ScrapeJob.objects.create(
        owner=owner,
        created_by=owner,
        updated_by=owner,
        name=unique_name(owner, name),
        slug=unique_slug(owner, name),
        status=JOB_STATUS_DRAFT,
        request_settings=_default_request(),
        pagination_settings=_default_pagination(),
        execution_settings=_default_execution(),
    )
    return job


def _default_request() -> dict:
    return {
        "timeout": 20,
        "wait_after_load_ms": 0,
        "wait_for_selector": "",
        "user_agent": "",
        "headers": {},
        "query": {},
        "follow_redirects": True,
        "verify_tls": True,
        "body": "",
    }


def _default_pagination() -> dict:
    return {
        "mode": "query_parameter",
        "variable": "page",
        "parameter": "page",
        "start": 1,
        "increment": 1,
        "maximum_pages": 100,
        "stop_conditions": [
            "no_result_items",
            "no_new_detail_urls",
            "repeated_page",
            "maximum_pages_reached",
        ],
    }


def _default_execution() -> dict:
    return {
        "delay_seconds": 0.5,
        "retries": 2,
        "max_run_seconds": 900,
    }


def apply_step(job: ScrapeJob, step: str, payload: dict, user) -> ScrapeJob:
    if step == "basic":
        name = (payload.get("name") or "").strip()
        if name:
            job.name = unique_name(job.owner, name, exclude_id=job.id) if name != job.name else name
            job.slug = unique_slug(job.owner, job.name, exclude_id=job.id)
        job.description = payload.get("description") or ""
        job.tags = [tag.strip() for tag in (payload.get("tags") or []) if str(tag).strip()]
        status = payload.get("status") or job.status
        if status == JOB_STATUS_ACTIVE:
            errors = validate_job_payload(_job_payload(job), activating=True)
            if errors:
                raise JobValidationError(errors)
        job.status = status
    elif step == "source":
        start_url = (payload.get("start_url") or "").strip()
        if start_url:
            validate_url(start_url, resolve=False)
        job.start_url = start_url
        job.url_template = (payload.get("url_template") or infer_page_template(start_url) or "").strip()
        job.http_method = payload.get("http_method") or job.http_method
        job.rendering_mode = payload.get("rendering_mode") or job.rendering_mode
        settings = dict(job.request_settings or {})
        for key in (
            "timeout",
            "wait_after_load_ms",
            "wait_for_selector",
            "user_agent",
            "headers",
            "query",
            "follow_redirects",
            "verify_tls",
            "body",
        ):
            if key in payload:
                settings[key] = payload[key]
        job.request_settings = settings
    elif step == "results":
        apply_result_selection(job, payload, via=ORIGIN_MANUAL)
        job.duplicate_handling = payload.get("duplicate_handling") or job.duplicate_handling
    elif step == "pagination":
        settings = dict(job.pagination_settings or {})
        settings.update({k: v for k, v in payload.items() if k != "url_template"})
        job.pagination_settings = settings
        if payload.get("url_template"):
            job.url_template = payload["url_template"]
        if payload.get("maximum_pages") not in (None, ""):
            job.maximum_pages = int(payload["maximum_pages"])
    elif step == "execution":
        settings = dict(job.execution_settings or {})
        settings.update(payload)
        job.execution_settings = settings
        if payload.get("maximum_pages") not in (None, ""):
            job.maximum_pages = int(payload["maximum_pages"])
        if payload.get("maximum_records") not in (None, ""):
            job.maximum_records = int(payload["maximum_records"])
    job.wizard_step = step
    job.updated_by = user
    job.version += 1
    job.save()
    return job


def save_variable(job: ScrapeJob, item: dict, *, via: str = ORIGIN_MANUAL) -> VariableParameter:
    payload = normalize_variable(item, via=via)
    name = payload["name"] or field_name_from_label(payload.get("label") or "variable")
    payload["name"] = name
    current = VariableParameter.objects.filter(job=job, name=name).first()
    created_via = payload.get("created_via") or (current.created_via if current else via)
    last_updated_via = payload.get("last_updated_via") or via
    values = {
        "label": payload["label"],
        "source_type": payload["source_type"],
        "scope": payload["scope"],
        "selector": payload["selector"],
        "value_from": payload["value_from"],
        "attribute_name": payload["attribute_name"],
        "data_type": payload["data_type"],
        "configuration": payload["configuration"],
        "transformations": payload["transformations"],
        "default_value": payload["default_value"],
        "required": payload["required"],
        "multiple": payload["multiple"],
        "unique": payload["unique"],
        "sort_order": payload["sort_order"],
        "created_via": created_via,
        "last_updated_via": last_updated_via,
    }
    if current:
        for key, value in values.items():
            setattr(current, key, value)
        current.save()
        return current
    return VariableParameter.objects.create(job=job, name=name, **values)


def save_field(job: ScrapeJob, item: dict, *, via: str = ORIGIN_MANUAL) -> ScrapeField:
    payload = normalize_field(item, via=via)
    name = payload["name"] or field_name_from_label(payload.get("label") or "field")
    payload["name"] = name
    current = ScrapeField.objects.filter(job=job, name=name).first()
    created_via = payload.get("created_via") or (current.created_via if current else via)
    last_updated_via = payload.get("last_updated_via") or via
    values = {
        "label": payload["label"],
        "description": payload["description"],
        "scope": payload["scope"],
        "selector": payload["selector"],
        "extraction_method": payload["extraction_method"],
        "attribute_name": payload["attribute_name"],
        "data_type": payload["data_type"],
        "transformations": payload["transformations"],
        "default_value": payload["default_value"],
        "required": payload["required"],
        "multiple": payload["multiple"],
        "unique": payload["unique"],
        "include_in_csv": payload["include_in_csv"],
        "include_in_sqlite": payload["include_in_sqlite"],
        "sort_order": payload["sort_order"],
        "created_via": created_via,
        "last_updated_via": last_updated_via,
    }
    if current:
        for key, value in values.items():
            setattr(current, key, value)
        current.save()
        return current
    return ScrapeField.objects.create(job=job, name=name, **values)


def apply_result_selection(job: ScrapeJob, payload: dict, *, via: str = ORIGIN_MANUAL) -> ScrapeJob:
    if "result_selector" in payload:
        job.result_selector = payload.get("result_selector") or ""
    if "result_list_selector" in payload:
        job.result_list_selector = payload.get("result_list_selector") or ""
    if "detail_link_selector" in payload:
        job.detail_link_selector = payload.get("detail_link_selector") or ""
    if "detail_link_attribute" in payload:
        job.detail_link_attribute = payload.get("detail_link_attribute") or "href"
    if "follow_detail_pages" in payload:
        job.follow_detail_pages = bool(payload.get("follow_detail_pages"))
    if "unique_field_name" in payload:
        job.unique_field_name = payload.get("unique_field_name") or ""
    if payload.get("maximum_records") not in (None, ""):
        job.maximum_records = int(payload["maximum_records"])
    if payload.get("maximum_pages") not in (None, ""):
        job.maximum_pages = int(payload["maximum_pages"])
        settings = dict(job.pagination_settings or {})
        settings["maximum_pages"] = job.maximum_pages
        if payload.get("pagination_mode"):
            settings["mode"] = payload["pagination_mode"]
        job.pagination_settings = settings
    if payload.get("wait_for_selector"):
        request = dict(job.request_settings or {})
        request["wait_for_selector"] = payload["wait_for_selector"]
        job.request_settings = request
    meta = dict(job.origin_meta or {})
    selection = dict(meta.get("result_selection") or {})
    selection.setdefault("created_via", via)
    selection["last_updated_via"] = via
    meta["result_selection"] = selection
    job.origin_meta = meta
    return job


def replace_variables(job: ScrapeJob, items: list[dict], *, via: str = ORIGIN_MANUAL) -> None:
    keep = {item.get("name") for item in items if item.get("name")}
    if keep:
        VariableParameter.objects.filter(job=job).exclude(name__in=keep).delete()
    else:
        VariableParameter.objects.filter(job=job).delete()
    for index, item in enumerate(items):
        payload = dict(item)
        payload.setdefault("sort_order", item.get("sort_order", index))
        payload.setdefault("last_updated_via", via)
        save_variable(job, payload, via=via)


def replace_fields(job: ScrapeJob, items: list[dict], *, via: str = ORIGIN_MANUAL) -> None:
    keep = {item.get("name") for item in items if item.get("name")}
    if keep:
        ScrapeField.objects.filter(job=job).exclude(name__in=keep).delete()
    else:
        ScrapeField.objects.filter(job=job).delete()
    for index, item in enumerate(items):
        payload = dict(item)
        payload.setdefault("sort_order", item.get("sort_order", index))
        payload.setdefault("last_updated_via", via)
        save_field(job, payload, via=via)


def _job_payload(job: ScrapeJob) -> dict:
    from .snapshots import snapshot_job

    data = snapshot_job(job)
    data["status"] = job.status
    return data


def job_to_wizard(job: ScrapeJob) -> dict:
    from .snapshots import snapshot_job

    data = snapshot_job(job)
    data.update(
        {
            "status": job.status,
            "tags": job.tags or [],
            "description": job.description,
            "wizard_step": job.wizard_step,
            "display_id": job.display_id,
        }
    )
    return data
