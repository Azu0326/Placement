"""CSV and SQLite exporters. Files stay in a controlled export directory."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.utils.text import slugify

from scraper.constants import (
    DATA_BOOLEAN,
    DATA_CURRENCY,
    DATA_DECIMAL,
    DATA_INTEGER,
    EXPORT_CSV,
    EXPORT_READY,
    EXPORT_RUNNING,
    EXPORT_SQLITE,
    RECORD_VALID,
    SCHEMA_VERSION,
    SCRAPOS_VERSION,
    SYSTEM_EXPORT_COLUMNS,
)
from scraper.models import ExportArtifact, ScrapedRecord, ScrapeRun

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
SAFE_IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _export_root() -> Path:
    root = Path(getattr(settings, "SCRAPER_EXPORT_DIRECTORY", Path(settings.BASE_DIR) / "var" / "exports"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(job_slug: str, run_id: str, suffix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = slugify(job_slug)[:60] or "job"
    run_part = str(run_id).split("-")[0]
    return f"{slug}_{run_part}_{stamp}.{suffix}"


def _formula_safe(value: str) -> str:
    if value and value[0] in FORMULA_PREFIXES:
        return f"'{value}"
    return value


def _serialize(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _field_specs(snapshot: dict, fmt: str) -> list[dict]:
    key = "include_in_csv" if fmt == EXPORT_CSV else "include_in_sqlite"
    fields = [item for item in snapshot.get("fields") or [] if item.get(key, True)]
    fields.sort(key=lambda item: item.get("sort_order") or 0)
    return fields


def _record_queryset(run: ScrapeRun, scope: str):
    qs = run.records.all().order_by("sequence_number")
    if scope == "valid":
        qs = qs.filter(status=RECORD_VALID)
    return qs.iterator(chunk_size=200)


def _row(record: ScrapedRecord, fields: list[dict]) -> dict:
    data = record.normalized_data or {}
    row = {name: _serialize(data.get(field["name"])) for field, name in ((f, f["name"]) for f in fields)}
    row["_record_id"] = str(record.id)
    row["_source_url"] = record.source_url
    row["_source_page"] = record.source_page or ""
    row["_scraped_at"] = record.scraped_at.isoformat() if record.scraped_at else ""
    row["_validation_status"] = record.status
    return row


def request_export(run: ScrapeRun, fmt: str, *, requested_by, scope: str = "all") -> ExportArtifact:
    suffix = "csv" if fmt == EXPORT_CSV else "sqlite3"
    file_name = _safe_filename(run.snapshot.get("slug") or run.job.slug, run.id, suffix)
    artifact = ExportArtifact.objects.create(
        run=run,
        format=fmt,
        status=EXPORT_RUNNING,
        file_name=file_name,
        storage_name=f"{run.id}/{file_name}",
        requested_by=requested_by,
    )
    try:
        path = _export_root() / str(run.id)
        path.mkdir(parents=True, exist_ok=True)
        target = path / file_name
        count = generate_csv(run, target, scope=scope) if fmt == EXPORT_CSV else generate_sqlite(run, target, scope=scope)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        hours = getattr(settings, "SCRAPER_EXPORT_RETENTION_HOURS", 72)
        expires = datetime.now(timezone.utc)
        from datetime import timedelta

        artifact.size_bytes = target.stat().st_size
        artifact.checksum = digest
        artifact.record_count = count
        artifact.status = EXPORT_READY
        artifact.expires_at = expires + timedelta(hours=hours)
        artifact.save()
    except Exception as exc:
        artifact.status = "failed"
        artifact.error_message = str(exc)[:500]
        artifact.save(update_fields=["status", "error_message"])
        raise
    return artifact


def generate_csv(run: ScrapeRun, path: Path, *, scope: str = "all") -> int:
    fields = _field_specs(run.snapshot, EXPORT_CSV)
    columns = [item["name"] for item in fields] + list(SYSTEM_EXPORT_COLUMNS)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in _record_queryset(run, scope):
            row = _row(record, fields)
            writer.writerow({key: _formula_safe(_serialize(row.get(key))) for key in columns})
            count += 1
    return count


def _sqlite_type(data_type: str) -> str:
    if data_type == DATA_INTEGER:
        return "INTEGER"
    if data_type in {DATA_DECIMAL, DATA_CURRENCY}:
        return "REAL"
    if data_type == DATA_BOOLEAN:
        return "INTEGER"
    return "TEXT"


def _ident(name: str) -> str:
    if not name or any(ch not in SAFE_IDENT for ch in name) or name[0].isdigit():
        raise ValueError(f"Unsafe identifier: {name}")
    return name


def generate_sqlite(run: ScrapeRun, path: Path, *, scope: str = "all") -> int:
    fields = _field_specs(run.snapshot, EXPORT_SQLITE)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        columns = ", ".join(
            [f"{_ident(item['name'])} {_sqlite_type(item.get('data_type') or 'text')}" for item in fields]
            + [
                "_record_id TEXT",
                "_source_url TEXT",
                "_source_page INTEGER",
                "_scraped_at TEXT",
                "_validation_status TEXT",
            ]
        )
        conn.execute(f"CREATE TABLE results ({columns})")
        conn.execute(
            "CREATE TABLE export_metadata (job_id TEXT, job_name TEXT, run_id TEXT, export_time TEXT, record_count INTEGER, scrapos_version TEXT, schema_version INTEGER)"
        )
        conn.execute("CREATE TABLE job_configuration (json TEXT)")
        conn.execute(
            "CREATE TABLE field_definitions (name TEXT, label TEXT, data_type TEXT, scope TEXT, selector TEXT)"
        )
        placeholders = ",".join("?" for _ in range(len(fields) + 5))
        insert_sql = f"INSERT INTO results VALUES ({placeholders})"
        count = 0
        for record in _record_queryset(run, scope):
            row = _row(record, fields)
            values = [row.get(item["name"]) for item in fields] + [
                row["_record_id"],
                row["_source_url"],
                row["_source_page"] or None,
                row["_scraped_at"],
                row["_validation_status"],
            ]
            conn.execute(insert_sql, values)
            count += 1
        conn.execute(
            "INSERT INTO export_metadata VALUES (?,?,?,?,?,?,?)",
            (
                str(run.job_id),
                run.snapshot.get("name") or run.job.name,
                str(run.id),
                datetime.now(timezone.utc).isoformat(),
                count,
                SCRAPOS_VERSION,
                SCHEMA_VERSION,
            ),
        )
        conn.execute("INSERT INTO job_configuration VALUES (?)", (json.dumps(run.snapshot, default=str),))
        conn.executemany(
            "INSERT INTO field_definitions VALUES (?,?,?,?,?)",
            [
                (item["name"], item.get("label"), item.get("data_type"), item.get("scope"), item.get("selector"))
                for item in fields
            ],
        )
        conn.commit()
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {ok}")
    finally:
        conn.close()
    return count


def artifact_path(artifact: ExportArtifact) -> Path:
    return _export_root() / artifact.storage_name
