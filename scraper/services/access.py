"""Ownership scoping for every scraper object."""

from __future__ import annotations

from django.http import Http404

from scraper.models import ExportArtifact, ScrapeJob, ScrapeRun, ScrapedRecord


def jobs_for(user):
    return ScrapeJob.objects.filter(owner=user)


def get_job(user, job_id) -> ScrapeJob:
    try:
        return jobs_for(user).get(pk=job_id)
    except ScrapeJob.DoesNotExist as exc:
        raise Http404("No such job.") from exc


def runs_for(user):
    return ScrapeRun.objects.filter(job__owner=user)


def get_run(user, run_id, job=None) -> ScrapeRun:
    qs = runs_for(user)
    if job is not None:
        qs = qs.filter(job=job)
    try:
        return qs.get(pk=run_id)
    except ScrapeRun.DoesNotExist as exc:
        raise Http404("No such run.") from exc


def records_for(user):
    return ScrapedRecord.objects.filter(job__owner=user)


def get_record(user, record_id, run=None) -> ScrapedRecord:
    qs = records_for(user)
    if run is not None:
        qs = qs.filter(run=run)
    try:
        return qs.get(pk=record_id)
    except ScrapedRecord.DoesNotExist as exc:
        raise Http404("No such record.") from exc


def get_export(user, export_id) -> ExportArtifact:
    try:
        return ExportArtifact.objects.filter(run__job__owner=user).get(pk=export_id)
    except ExportArtifact.DoesNotExist as exc:
        raise Http404("No such export.") from exc
