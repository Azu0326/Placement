"""HTML views and JSON endpoints for scraper jobs."""

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView

from authentication.permissions import RoleRequiredMixin
from authentication.roles import ROLE_EDITOR, ROLE_VIEWER
from scraper.constants import (
    DISPLAY_COMPLETED,
    DISPLAY_FAILED,
    DISPLAY_QUEUED,
    DISPLAY_RUNNING,
    EXPORT_CSV,
    EXPORT_SQLITE,
    JOB_STATUS_ARCHIVED,
    RECORD_FAILED,
    RUN_FAILED,
    WIZARD_STEPS,
)
from scraper.models import ExportArtifact, PageTestCache, ScrapeField, ScrapeJob, ScrapeRun, VariableParameter
from scraper.services import access
from scraper.services.exporters import artifact_path, request_export
from scraper.services.fetcher import fetch_page
from scraper.services.html_parser import looks_like_javascript_app
from scraper.services.html_sanitize import sanitize_html
from scraper.services.http_fetcher import FetchError
from scraper.services.config_csv import (
    CsvConfigError,
    apply_import,
    errors_csv,
    export_job_csv,
    preview_counter,
    preview_import,
    template_csv,
)
from scraper.services.jobs import apply_step, create_draft, job_to_wizard, replace_fields, replace_variables
from scraper.services.orchestrator import request_cancel, request_pause
from scraper.services.queue import enqueue
from scraper.services.selector_tester import test_selector
from scraper.services.snapshots import snapshot_job
from scraper.services.ssrf import RequestPolicyError
from scraper.services.url_template import infer_page_template
from scraper.services.validation import JobValidationError, field_name_from_label, validate_job_payload
from scraper.throttling import Throttled, check as throttle_check

from . import constants as C


class ViewerView(RoleRequiredMixin, TemplateView):
    required_role = ROLE_VIEWER
    nav_group = "g-scraper"
    nav_key = ""
    crumb = ""
    page_title = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            {
                "nav_key": self.nav_key,
                "nav_group": self.nav_group,
                "crumb": self.crumb,
                "page_title": self.page_title,
            }
        )
        return ctx


class EditorView(ViewerView):
    required_role = ROLE_EDITOR


class JobListView(ViewerView):
    template_name = "scraper/jobs.html"
    nav_key = "jobs"
    crumb = "Scraper / Jobs"
    page_title = "Scraper jobs"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = access.jobs_for(self.request.user).exclude(status=JOB_STATUS_ARCHIVED)
        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(start_url__icontains=q) | Q(slug__icontains=q))
        if status:
            qs = qs.filter(status=status)
        paginator = Paginator(qs, 20)
        page = paginator.get_page(self.request.GET.get("page") or 1)
        rows = []
        for job in page.object_list:
            last = job.runs.order_by("-created_at").first()
            rows.append({"job": job, "last_run": last})
        ctx.update(
            {
                "page_obj": page,
                "rows": rows,
                "search": q,
                "status_filter": status,
                "show_queued_toast": self.request.GET.get("queued") == "1",
            }
        )
        return ctx


class JobCreateView(EditorView):
    nav_key = "newjob"

    def post(self, request, *args, **kwargs):
        job = create_draft(request.user, name=(request.POST.get("name") or "Untitled scraper").strip())
        return redirect("job_wizard", job_id=job.id)

    def get(self, request, *args, **kwargs):
        job = create_draft(request.user)
        return redirect("job_wizard", job_id=job.id)


class JobWizardView(EditorView):
    template_name = "scraper/job_wizard.html"
    nav_key = "newjob"
    page_title = "New scraper job"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = access.get_job(self.request.user, kwargs["job_id"])
        ctx.update(
            {
                "job": job,
                "wizard": job_to_wizard(job),
                "steps": WIZARD_STEPS,
                "crumb": f"Scraper / Jobs / {job.name}",
                "constants": {
                    "steps": [{"key": key, "label": label} for key, label in WIZARD_STEPS],
                    "source_types": C.SOURCE_TYPE_CHOICES,
                    "scopes": C.SCOPE_CHOICES,
                    "value_from": C.VALUE_FROM_CHOICES,
                    "data_types": C.DATA_TYPE_CHOICES,
                    "pagination_modes": C.PAGINATION_MODE_CHOICES,
                    "render_modes": C.RENDER_MODE_CHOICES,
                    "http_methods": C.HTTP_METHOD_CHOICES,
                    "job_statuses": C.JOB_STATUS_CHOICES,
                    "duplicate_handling": C.DUPLICATE_HANDLING_CHOICES,
                },
            }
        )
        return ctx


class JobDetailView(ViewerView):
    template_name = "scraper/job_detail.html"
    nav_key = "detail"
    page_title = "Job detail"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = access.get_job(self.request.user, kwargs["job_id"])
        runs = job.runs.all()[:20]
        last = job.runs.order_by("-created_at").first()
        records = last.records.all()[:50] if last else []
        ctx.update(
            {
                "job": job,
                "wizard": job_to_wizard(job),
                "runs": runs,
                "last_run": last,
                "records": records,
                "crumb": f"Scraper / Jobs / {job.name}",
            }
        )
        return ctx


class RunDetailView(ViewerView):
    template_name = "scraper/run_detail.html"
    nav_key = "execution"
    page_title = "Run"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = access.get_job(self.request.user, kwargs["job_id"])
        run = access.get_run(self.request.user, kwargs["run_id"], job=job)
        events = run.events.order_by("-created_at")[:40]
        ctx.update(
            {
                "job": job,
                "run": run,
                "events": events,
                "crumb": f"Scraper / Jobs / {job.name} / {run.display_id}",
            }
        )
        return ctx


class RunRecordsView(ViewerView):
    template_name = "scraper/results.html"
    nav_key = "detail"
    page_title = "Results"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = access.get_job(self.request.user, kwargs["job_id"])
        run = access.get_run(self.request.user, kwargs["run_id"], job=job)
        qs = run.records.all()
        q = (self.request.GET.get("q") or "").strip()
        status = (self.request.GET.get("status") or "").strip()
        if q:
            qs = qs.filter(
                Q(normalized_data__icontains=q)
                | Q(source_url__icontains=q)
                | Q(detail_url__icontains=q)
                | Q(unique_key__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        sort = self.request.GET.get("sort") or "sequence_number"
        if sort.lstrip("-") in {"sequence_number", "scraped_at", "status", "source_page"}:
            qs = qs.order_by(sort)
        paginator = Paginator(qs, 25)
        page = paginator.get_page(self.request.GET.get("page") or 1)
        fields = run.snapshot.get("fields") or []
        rows = []
        for record in page.object_list:
            data = record.normalized_data or record.raw_data or {}
            rows.append({"record": record, "values": [data.get(field.get("name")) for field in fields]})
        ctx.update(
            {
                "job": job,
                "run": run,
                "page_obj": page,
                "result_rows": rows,
                "fields": fields,
                "search": q,
                "status_filter": status,
                "crumb": f"Scraper / Jobs / {job.name} / Results",
            }
        )
        return ctx


class ExecutionView(ViewerView):
    template_name = "scraper/execution.html"
    nav_key = "execution"
    crumb = "Scraper / Execution"
    page_title = "Execution monitor"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        runs = access.runs_for(self.request.user).select_related("job")
        today = timezone.now().date()
        ctx.update(
            {
                "active_runs": runs.filter(status__in=C.ACTIVE_RUN_STATUSES)[:10],
                "recent_runs": runs[:20],
                "queued_count": runs.filter(status=C.RUN_QUEUED).count(),
                "running_count": runs.filter(status__in={C.RUN_RUNNING, C.RUN_PREPARING}).count(),
                "completed_today": runs.filter(
                    status__in={C.RUN_COMPLETED, C.RUN_COMPLETED_WITH_ERRORS},
                    finished_at__date=today,
                ).count(),
                "failed_today": runs.filter(status=C.RUN_FAILED, finished_at__date=today).count(),
            }
        )
        return ctx


def _json_error(message, status=400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _json_ok(**payload):
    data = {"ok": True}
    data.update(payload)
    return JsonResponse(data)


@method_decorator(require_POST, name="dispatch")
class WizardStepAPI(EditorView):
    def post(self, request, job_id, step):
        job = access.get_job(request.user, job_id)
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return _json_error("Invalid JSON.")
        try:
            apply_step(job, step, payload, request.user)
            if "variables" in payload:
                replace_variables(job, payload["variables"])
            if "fields" in payload:
                replace_fields(job, payload["fields"])
        except (JobValidationError, RequestPolicyError, ValueError) as exc:
            errors = getattr(exc, "errors", [str(exc)])
            return _json_error("Validation failed.", errors=errors)
        return _json_ok(job=job_to_wizard(job))


@require_GET
def config_csv_template(request):
    if not request.user.is_authenticated:
        return _json_error("Authentication required.", status=401)
    response = HttpResponse(template_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="scrapos_configuration_template.csv"'
    return response


@require_GET
def config_csv_export(request, job_id):
    if not request.user.is_authenticated:
        return _json_error("Authentication required.", status=401)
    job = access.get_job(request.user, job_id)
    slug = job.slug or "job"
    response = HttpResponse(export_job_csv(job), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{slug}_configuration.csv"'
    return response


def _read_csv_upload(request) -> bytes:
    upload = request.FILES.get("file")
    if upload is not None:
        return upload.read()
    if request.content_type == "application/json":
        payload = json.loads(request.body or "{}")
        text = payload.get("csv") or ""
        return text.encode("utf-8")
    return (request.POST.get("csv") or "").encode("utf-8")


def _preview_payload(preview: dict) -> dict:
    rows = []
    for row in preview["rows"]:
        rows.append(
            {
                "csv_row": row["csv_row"],
                "row_type": row["row_type"],
                "name": row["name"],
                "display_label": row["display_label"],
                "source": row["source"],
                "selector": row["selector"],
                "data_type": row["data_type"],
                "action": row.get("action"),
                "valid": row["valid"],
                "enabled": row["enabled"],
                "errors": row["errors"],
                "warnings": row["warnings"],
            }
        )
    return {
        "mode": preview["mode"],
        "rows": rows,
        "errors": preview["errors"],
        "warnings": preview["warnings"],
        "summary": preview["summary"],
        "kept_rows": preview["kept_rows"],
        "deleted_rows": preview["deleted_rows"],
        "can_import": preview["can_import"],
        "error_csv": preview["error_csv"],
    }


@method_decorator(require_POST, name="dispatch")
class ConfigCsvPreviewAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        try:
            throttle_check(
                f"csv:{request.user.pk}",
                limit=getattr(settings, "SCRAPER_TEST_RATE_LIMIT", 20),
                window_seconds=60,
            )
        except Throttled:
            return _json_error("Too many CSV requests. Try again shortly.", status=429)
        try:
            content = _read_csv_upload(request)
            if not content.strip():
                return _json_error("Choose a CSV file.")
            mode = request.POST.get("mode") or (json.loads(request.body or "{}").get("mode") if request.content_type == "application/json" else "merge")
            preview = preview_import(job, content, mode=mode or "merge")
        except CsvConfigError as exc:
            return _json_error(str(exc), errors=exc.errors, error_csv=errors_csv(exc.errors))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _json_error("The CSV could not be read as UTF-8.")
        return _json_ok(**_preview_payload(preview))


@method_decorator(require_POST, name="dispatch")
class ConfigCsvImportAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        try:
            throttle_check(
                f"csv:{request.user.pk}",
                limit=getattr(settings, "SCRAPER_TEST_RATE_LIMIT", 20),
                window_seconds=60,
            )
        except Throttled:
            return _json_error("Too many CSV requests. Try again shortly.", status=429)
        payload = {}
        if request.content_type == "application/json":
            try:
                payload = json.loads(request.body or "{}")
            except json.JSONDecodeError:
                return _json_error("Invalid JSON.")
        mode = request.POST.get("mode") or payload.get("mode") or "merge"
        confirm = str(request.POST.get("confirm_replace") or payload.get("confirm_replace") or "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            content = _read_csv_upload(request)
            if not content.strip():
                return _json_error("Choose a CSV file.")
            result = apply_import(job, content, mode=mode, confirm_replace=confirm, user=request.user)
        except CsvConfigError as exc:
            return _json_error(str(exc), errors=exc.errors, error_csv=errors_csv(exc.errors))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_error("The CSV could not be read as UTF-8.")
        return _json_ok(job=job_to_wizard(job), summary=result["summary"])


@method_decorator(require_POST, name="dispatch")
class ConfigCsvErrorsAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        try:
            content = _read_csv_upload(request)
            preview = preview_import(job, content, mode=request.POST.get("mode") or "merge")
        except CsvConfigError as exc:
            text = errors_csv(exc.errors)
        else:
            text = preview["error_csv"]
        response = HttpResponse(text, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="configuration_import_errors.csv"'
        return response


@method_decorator(require_POST, name="dispatch")
class TestVariableAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        payload = json.loads(request.body or "{}")
        source = payload.get("source_type") or payload.get("source") or ""
        if source in {"counter", "page_number", "current_page_number"}:
            return _json_ok(**preview_counter(job, payload))
        return _json_error("Use Test selector for HTML variables.")


@method_decorator(require_POST, name="dispatch")
class TestPageAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        try:
            throttle_check(
                f"test:{request.user.pk}:{request.META.get('REMOTE_ADDR')}",
                limit=getattr(settings, "SCRAPER_TEST_RATE_LIMIT", 20),
                window_seconds=60,
            )
        except Throttled:
            return _json_error("Too many test requests. Try again shortly.", status=429)
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return _json_error("Invalid JSON.")
        url = (payload.get("url") or job.start_url or "").strip()
        request_settings = {**(job.request_settings or {}), **(payload.get("request_settings") or {})}
        try:
            result = fetch_page(
                url,
                rendering_mode=payload.get("rendering_mode") or job.rendering_mode,
                method=payload.get("http_method") or job.http_method,
                timeout=request_settings.get("timeout"),
                wait_after_load_ms=int(request_settings.get("wait_after_load_ms") or 0),
                wait_for_selector=request_settings.get("wait_for_selector") or "",
                user_agent=request_settings.get("user_agent") or "",
                headers=request_settings.get("headers") or {},
                follow_redirects=request_settings.get("follow_redirects", True),
                verify_tls=request_settings.get("verify_tls", True),
            )
        except RequestPolicyError as exc:
            return _json_error(str(exc), status=400)
        except FetchError as exc:
            return _json_error(str(exc), status=400, blocked=exc.blocked, status_code=exc.status_code)
        js_likely = looks_like_javascript_app(result.html, job.result_selector)
        cache = PageTestCache.objects.create(
            owner=request.user,
            job=job,
            requested_url=url,
            final_url=result.final_url,
            status_code=result.status_code,
            content_type=result.content_type,
            duration_ms=result.duration_ms,
            rendering_mode_used=result.rendering_mode,
            javascript_likely=js_likely,
            sanitized_html=sanitize_html(result.html),
        )
        inferred = infer_page_template(result.final_url or url)
        return _json_ok(
            test_id=str(cache.id),
            status_code=result.status_code,
            content_type=result.content_type,
            final_url=result.final_url,
            duration_ms=result.duration_ms,
            rendering_mode=result.rendering_mode,
            javascript_likely=js_likely,
            html=cache.sanitized_html[:50_000],
            inferred_url_template=inferred,
        )


@method_decorator(require_POST, name="dispatch")
class TestSelectorAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        payload = json.loads(request.body or "{}")
        html = ""
        cache = (
            PageTestCache.objects.filter(owner=request.user, job=job)
            .order_by("-created_at")
            .first()
        )
        if cache:
            html = cache.sanitized_html
        if payload.get("refetch") or not html:
            try:
                result = fetch_page(
                    payload.get("url") or job.start_url,
                    rendering_mode=payload.get("rendering_mode") or job.rendering_mode,
                    wait_for_selector=payload.get("selector") or job.result_selector,
                )
                html = result.html
            except (FetchError, RequestPolicyError) as exc:
                return _json_error(str(exc))
        preview = test_selector(
            html,
            payload.get("selector") or "",
            scope_selector=payload.get("scope_selector") or "",
            value_from=payload.get("value_from") or "text_content",
            attribute_name=payload.get("attribute_name") or "",
            transformations=payload.get("transformations") or [],
            multiple=payload.get("multiple", True),
            base_url=payload.get("url") or job.start_url,
        )
        return _json_ok(**preview)


@method_decorator(require_POST, name="dispatch")
class StartRunAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        try:
            throttle_check(
                f"run:{request.user.pk}",
                limit=getattr(settings, "SCRAPER_RUN_RATE_LIMIT", 10),
                window_seconds=60,
            )
        except Throttled:
            return _json_error("Too many run requests.", status=429)
        payload = snapshot_job(job)
        errors = validate_job_payload({**payload, "status": job.status}, activating=True)
        if errors:
            return _json_error("The job is not ready to run.", errors=errors)
        run = ScrapeRun.objects.create(
            job=job,
            job_version=job.version,
            snapshot=payload,
            requested_by=request.user,
        )
        enqueue(run)
        job.last_run_at = timezone.now()
        job.save(update_fields=["last_run_at"])
        return _json_ok(
            run_id=str(run.id),
            display_id=run.display_id,
            redirect=reverse("run_detail", args=[job.id, run.id]),
        )


@method_decorator(require_POST, name="dispatch")
class RunActionAPI(EditorView):
    def post(self, request, job_id, run_id, action):
        job = access.get_job(request.user, job_id)
        run = access.get_run(request.user, run_id, job=job)
        if action == "cancel":
            request_cancel(run)
        elif action == "pause":
            request_pause(run)
        elif action == "retry":
            if run.status != RUN_FAILED and run.display_status != DISPLAY_FAILED:
                return _json_error("Only a failed run can be retried.")
            clone = ScrapeRun.objects.create(
                job=job,
                job_version=job.version,
                snapshot=run.snapshot,
                requested_by=request.user,
            )
            enqueue(clone)
            if request.content_type != "application/json":
                return redirect("run_detail", job.id, clone.id)
            return _json_ok(run_id=str(clone.id), redirect=reverse("run_detail", args=[job.id, clone.id]))
        else:
            return _json_error("Unknown action.")
        run.refresh_from_db()
        if request.content_type != "application/json":
            return redirect("run_detail", job.id, run.id)
        return _json_ok(status=run.status, display_status=run.display_status)


@require_GET
def run_status_api(request, job_id, run_id):
    if not request.user.is_authenticated:
        return _json_error("Authentication required.", status=401)
    job = access.get_job(request.user, job_id)
    run = access.get_run(request.user, run_id, job=job)
    events = [
        {
            "level": event.level,
            "type": event.event_type,
            "message": event.message,
            "at": event.created_at.isoformat(),
        }
        for event in run.events.order_by("-created_at")[:30]
    ]
    return _json_ok(
        status=run.status,
        display_status=run.display_status,
        phase=run.current_phase,
        current_page=run.current_page,
        pages_completed=run.pages_completed,
        pages_attempted=run.pages_attempted,
        records_discovered=run.records_discovered,
        records_created=run.records_created,
        records_skipped=run.records_skipped,
        records_failed=run.records_failed,
        detail_pages_queued=run.detail_pages_queued,
        detail_pages_completed=run.detail_pages_completed,
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        error_summary=run.error_summary,
        events=events,
    )


@method_decorator(require_POST, name="dispatch")
class ExportCreateAPI(EditorView):
    def post(self, request, job_id, run_id):
        job = access.get_job(request.user, job_id)
        run = access.get_run(request.user, run_id, job=job)
        try:
            payload = json.loads(request.body.decode() or "{}") if request.content_type == "application/json" else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        fmt = payload.get("format") or request.POST.get("format")
        if fmt not in {EXPORT_CSV, EXPORT_SQLITE}:
            return _json_error("Choose csv or sqlite.")
        scope = payload.get("scope") or request.POST.get("scope") or "all"
        artifact = request_export(run, fmt, requested_by=request.user, scope=scope)
        download = reverse("export_download", args=[job.id, run.id, artifact.id])
        if request.content_type != "application/json":
            return redirect(download)
        return _json_ok(
            export_id=str(artifact.id),
            status=artifact.status,
            file_name=artifact.file_name,
            download=download,
        )


@require_GET
def export_download(request, job_id, run_id, export_id):
    job = access.get_job(request.user, job_id)
    access.get_run(request.user, run_id, job=job)
    artifact = access.get_export(request.user, export_id)
    path = artifact_path(artifact)
    if not path.exists() or artifact.status != C.EXPORT_READY:
        return _json_error("That export is not available.", status=404)
    content = "text/csv" if artifact.format == EXPORT_CSV else "application/vnd.sqlite3"
    return FileResponse(path.open("rb"), as_attachment=True, filename=artifact.file_name, content_type=content)


@method_decorator(require_POST, name="dispatch")
class JobArchiveAPI(EditorView):
    def post(self, request, job_id):
        job = access.get_job(request.user, job_id)
        job.status = JOB_STATUS_ARCHIVED
        job.save(update_fields=["status", "updated_at"])
        return _json_ok()


@require_GET
def validate_job_api(request, job_id):
    job = access.get_job(request.user, job_id)
    errors = validate_job_payload({**snapshot_job(job), "status": job.status}, activating=True)
    return _json_ok(errors=errors, ready=not errors)


@require_POST
def slugify_field_api(request):
    if not request.user.is_authenticated:
        return _json_error("Authentication required.", status=401)
    payload = json.loads(request.body or "{}")
    return _json_ok(name=field_name_from_label(payload.get("label") or ""))
