"""Immutable job configuration snapshots stored on each run."""

from __future__ import annotations

from scraper.models import ScrapeJob


def snapshot_job(job: ScrapeJob) -> dict:
    return {
        "id": str(job.id),
        "name": job.name,
        "slug": job.slug,
        "version": job.version,
        "start_url": job.start_url,
        "url_template": job.url_template,
        "http_method": job.http_method,
        "rendering_mode": job.rendering_mode,
        "request_settings": job.request_settings or {},
        "pagination_settings": job.pagination_settings or {},
        "execution_settings": job.execution_settings or {},
        "result_selector": job.result_selector,
        "result_list_selector": job.result_list_selector,
        "detail_link_selector": job.detail_link_selector,
        "detail_link_attribute": job.detail_link_attribute,
        "follow_detail_pages": job.follow_detail_pages,
        "unique_field_name": job.unique_field_name,
        "duplicate_handling": job.duplicate_handling,
        "maximum_pages": job.maximum_pages,
        "maximum_records": job.maximum_records,
        "variables": [
            {
                "name": item.name,
                "label": item.label,
                "source_type": item.source_type,
                "scope": item.scope,
                "selector": item.selector,
                "value_from": item.value_from,
                "attribute_name": item.attribute_name,
                "data_type": item.data_type,
                "configuration": item.configuration or {},
                "transformations": item.transformations or [],
                "default_value": item.default_value,
                "required": item.required,
                "multiple": item.multiple,
                "unique": item.unique,
                "sort_order": item.sort_order,
                "created_via": item.created_via,
                "last_updated_via": item.last_updated_via,
            }
            for item in job.variables.all()
        ],
        "fields": [
            {
                "name": item.name,
                "label": item.label,
                "description": item.description,
                "scope": item.scope,
                "selector": item.selector,
                "extraction_method": item.extraction_method,
                "attribute_name": item.attribute_name,
                "data_type": item.data_type,
                "transformations": item.transformations or [],
                "default_value": item.default_value,
                "required": item.required,
                "multiple": item.multiple,
                "unique": item.unique,
                "include_in_csv": item.include_in_csv,
                "include_in_sqlite": item.include_in_sqlite,
                "sort_order": item.sort_order,
                "created_via": item.created_via,
                "last_updated_via": item.last_updated_via,
            }
            for item in job.fields.all()
        ],
        "origin_meta": job.origin_meta or {},
    }
