"""Normalized scraper configuration, runs, records and exports."""

from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from . import constants as C


class ScrapeJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scrape_jobs",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220)
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20, choices=C.JOB_STATUS_CHOICES, default=C.JOB_STATUS_DRAFT
    )
    start_url = models.URLField(max_length=2000, blank=True)
    url_template = models.CharField(max_length=2000, blank=True)
    http_method = models.CharField(
        max_length=8, choices=C.HTTP_METHOD_CHOICES, default=C.HTTP_GET
    )
    rendering_mode = models.CharField(
        max_length=16, choices=C.RENDER_MODE_CHOICES, default=C.RENDER_AUTO
    )
    request_settings = models.JSONField(default=dict, blank=True)
    pagination_settings = models.JSONField(default=dict, blank=True)
    execution_settings = models.JSONField(default=dict, blank=True)
    result_selector = models.CharField(max_length=500, blank=True)
    result_list_selector = models.CharField(max_length=500, blank=True)
    detail_link_selector = models.CharField(max_length=500, blank=True)
    detail_link_attribute = models.CharField(max_length=80, default="href")
    follow_detail_pages = models.BooleanField(default=False)
    unique_field_name = models.CharField(max_length=80, blank=True)
    duplicate_handling = models.CharField(
        max_length=16, choices=C.DUPLICATE_HANDLING_CHOICES, default=C.DUPLICATE_SKIP
    )
    maximum_pages = models.PositiveIntegerField(null=True, blank=True)
    maximum_records = models.PositiveIntegerField(null=True, blank=True)
    origin_meta = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    wizard_step = models.CharField(max_length=32, default="basic")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_scrape_jobs",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_scrape_jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "slug"],
                name="scraper_job_owner_slug_unique",
            ),
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="scraper_job_owner_name_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["owner", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:200] or "job"
            self.slug = base
        super().save(*args, **kwargs)

    @property
    def display_id(self) -> str:
        return f"SJ-{str(self.id).split('-')[0].upper()}"


class VariableParameter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(ScrapeJob, on_delete=models.CASCADE, related_name="variables")
    name = models.CharField(max_length=80)
    label = models.CharField(max_length=160, blank=True)
    source_type = models.CharField(max_length=32, choices=C.SOURCE_TYPE_CHOICES)
    scope = models.CharField(
        max_length=24, choices=C.SCOPE_CHOICES, default=C.SCOPE_RESULT_PAGE
    )
    selector = models.CharField(max_length=500, blank=True)
    value_from = models.CharField(
        max_length=24, choices=C.VALUE_FROM_CHOICES, default=C.VALUE_TEXT
    )
    attribute_name = models.CharField(max_length=80, blank=True)
    data_type = models.CharField(
        max_length=24, choices=C.DATA_TYPE_CHOICES, default=C.DATA_TEXT
    )
    configuration = models.JSONField(default=dict, blank=True)
    transformations = models.JSONField(default=list, blank=True)
    default_value = models.JSONField(null=True, blank=True)
    required = models.BooleanField(default=False)
    multiple = models.BooleanField(default=False)
    unique = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_via = models.CharField(max_length=16, default="manual")
    last_updated_via = models.CharField(max_length=16, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "name"],
                name="scraper_variable_job_name_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ScrapeField(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(ScrapeJob, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=80)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    scope = models.CharField(
        max_length=24, choices=C.SCOPE_CHOICES, default=C.SCOPE_RESULT_ITEM
    )
    selector = models.CharField(max_length=500, blank=True)
    extraction_method = models.CharField(
        max_length=24, choices=C.VALUE_FROM_CHOICES, default=C.VALUE_TEXT
    )
    attribute_name = models.CharField(max_length=80, blank=True)
    data_type = models.CharField(
        max_length=24, choices=C.DATA_TYPE_CHOICES, default=C.DATA_TEXT
    )
    transformations = models.JSONField(default=list, blank=True)
    default_value = models.JSONField(null=True, blank=True)
    required = models.BooleanField(default=False)
    multiple = models.BooleanField(default=False)
    unique = models.BooleanField(default=False)
    include_in_csv = models.BooleanField(default=True)
    include_in_sqlite = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_via = models.CharField(max_length=16, default="manual")
    last_updated_via = models.CharField(max_length=16, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "name"],
                name="scraper_field_job_name_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ScrapeRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(ScrapeJob, on_delete=models.CASCADE, related_name="runs")
    display_number = models.PositiveIntegerField(editable=False)
    job_version = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="scrape_runs",
    )
    status = models.CharField(
        max_length=32, choices=C.RUN_STATUS_CHOICES, default=C.RUN_QUEUED
    )
    current_phase = models.CharField(max_length=32, blank=True)
    current_page = models.PositiveIntegerField(default=0)
    pages_attempted = models.PositiveIntegerField(default=0)
    pages_completed = models.PositiveIntegerField(default=0)
    records_discovered = models.PositiveIntegerField(default=0)
    records_created = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(default=0)
    records_failed = models.PositiveIntegerField(default=0)
    detail_pages_queued = models.PositiveIntegerField(default=0)
    detail_pages_completed = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["job", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["requested_by", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.display_id

    def save(self, *args, **kwargs):
        if not self.display_number:
            last = (
                ScrapeRun.objects.filter(job=self.job)
                .order_by("-display_number")
                .values_list("display_number", flat=True)
                .first()
            )
            self.display_number = (last or 0) + 1
        super().save(*args, **kwargs)

    @property
    def display_id(self) -> str:
        return f"SC-{self.display_number:04d}"

    @property
    def display_status(self) -> str:
        return C.RUN_DISPLAY_STATUS.get(self.status, C.DISPLAY_FAILED)


class ScrapedRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ScrapeRun, on_delete=models.CASCADE, related_name="records")
    job = models.ForeignKey(ScrapeJob, on_delete=models.CASCADE, related_name="records")
    sequence_number = models.PositiveIntegerField()
    unique_key = models.CharField(max_length=512, blank=True)
    source_url = models.URLField(max_length=2000, blank=True)
    source_page = models.PositiveIntegerField(null=True, blank=True)
    detail_url = models.URLField(max_length=2000, blank=True)
    detail_url_hash = models.CharField(max_length=64, blank=True, db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)
    normalized_data = models.JSONField(default=dict, blank=True)
    validation_errors = models.JSONField(default=list, blank=True)
    content_fingerprint = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=C.RECORD_STATUS_CHOICES, default=C.RECORD_VALID
    )
    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "unique_key"],
                condition=~models.Q(unique_key=""),
                name="scraper_record_run_unique_key",
            ),
        ]
        indexes = [
            models.Index(fields=["job", "scraped_at"]),
            models.Index(fields=["run", "status"]),
            models.Index(fields=["run", "unique_key"]),
            models.Index(fields=["detail_url_hash"]),
        ]

    def save(self, *args, **kwargs):
        if self.detail_url and not self.detail_url_hash:
            self.detail_url_hash = hashlib.sha256(self.detail_url.encode()).hexdigest()
        super().save(*args, **kwargs)


class ScrapeEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ScrapeRun, on_delete=models.CASCADE, related_name="events")
    level = models.CharField(max_length=16, choices=C.EVENT_LEVEL_CHOICES, default=C.EVENT_INFO)
    event_type = models.CharField(max_length=64)
    message = models.CharField(max_length=500)
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["run", "created_at"])]


class ExportArtifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ScrapeRun, on_delete=models.CASCADE, related_name="exports")
    format = models.CharField(max_length=16, choices=C.EXPORT_FORMAT_CHOICES)
    status = models.CharField(
        max_length=16, choices=C.EXPORT_STATUS_CHOICES, default=C.EXPORT_PENDING
    )
    file_name = models.CharField(max_length=255)
    storage_name = models.CharField(max_length=500)
    size_bytes = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="scrape_exports",
    )
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["run", "format", "status"])]


class PageTestCache(models.Model):
    """Short-lived sanitized HTML from Test Page, never logged in full."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="page_tests",
    )
    job = models.ForeignKey(
        ScrapeJob, on_delete=models.CASCADE, null=True, blank=True, related_name="page_tests"
    )
    requested_url = models.URLField(max_length=2000)
    final_url = models.URLField(max_length=2000, blank=True)
    status_code = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=160, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    rendering_mode_used = models.CharField(max_length=16, blank=True)
    javascript_likely = models.BooleanField(default=False)
    sanitized_html = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
