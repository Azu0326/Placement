from django.urls import path

from . import views

urlpatterns = [
    path("scraper/jobs/", views.JobListView.as_view(), name="jobs"),
    path("scraper/jobs/new/", views.JobCreateView.as_view(), name="job_new"),
    path("scraper/jobs/<uuid:job_id>/wizard/", views.JobWizardView.as_view(), name="job_wizard"),
    path("scraper/jobs/<uuid:job_id>/", views.JobDetailView.as_view(), name="job_detail"),
    path("scraper/jobs/<uuid:job_id>/runs/<uuid:run_id>/", views.RunDetailView.as_view(), name="run_detail"),
    path(
        "scraper/jobs/<uuid:job_id>/runs/<uuid:run_id>/records/",
        views.RunRecordsView.as_view(),
        name="run_records",
    ),
    path("scraper/execution/", views.ExecutionView.as_view(), name="execution"),
    path("scraper/api/field-name/", views.slugify_field_api, name="api_field_name"),
    path("scraper/api/config-csv/template/", views.config_csv_template, name="api_config_csv_template"),
    path(
        "scraper/api/ai/generate-config/",
        views.AIGenerateConfigAPI.as_view(),
        name="api_ai_generate_config",
    ),
    path("scraper/api/jobs/<uuid:job_id>/config.csv", views.config_csv_export, name="api_config_csv_export"),
    path(
        "scraper/api/jobs/<uuid:job_id>/config-csv/preview/",
        views.ConfigCsvPreviewAPI.as_view(),
        name="api_config_csv_preview",
    ),
    path(
        "scraper/api/jobs/<uuid:job_id>/config-csv/import/",
        views.ConfigCsvImportAPI.as_view(),
        name="api_config_csv_import",
    ),
    path(
        "scraper/api/jobs/<uuid:job_id>/config-csv/errors/",
        views.ConfigCsvErrorsAPI.as_view(),
        name="api_config_csv_errors",
    ),
    path(
        "scraper/api/jobs/<uuid:job_id>/test-variable/",
        views.TestVariableAPI.as_view(),
        name="api_test_variable",
    ),
    path("scraper/api/jobs/<uuid:job_id>/wizard/<slug:step>/", views.WizardStepAPI.as_view(), name="api_wizard_step"),
    path("scraper/api/jobs/<uuid:job_id>/test-page/", views.TestPageAPI.as_view(), name="api_test_page"),
    path("scraper/api/jobs/<uuid:job_id>/test-selector/", views.TestSelectorAPI.as_view(), name="api_test_selector"),
    path("scraper/api/jobs/<uuid:job_id>/validate/", views.validate_job_api, name="api_validate_job"),
    path("scraper/api/jobs/<uuid:job_id>/run/", views.StartRunAPI.as_view(), name="api_start_run"),
    path("scraper/api/jobs/<uuid:job_id>/archive/", views.JobArchiveAPI.as_view(), name="api_archive_job"),
    path(
        "scraper/api/jobs/<uuid:job_id>/runs/<uuid:run_id>/status/",
        views.run_status_api,
        name="api_run_status",
    ),
    path(
        "scraper/api/jobs/<uuid:job_id>/runs/<uuid:run_id>/export/",
        views.ExportCreateAPI.as_view(),
        name="api_export_create",
    ),
    path(
        "scraper/api/jobs/<uuid:job_id>/runs/<uuid:run_id>/records/<uuid:record_id>/facebook/",
        views.PublishScrapedFacebookAPI.as_view(),
        name="api_publish_facebook_record",
    ),
    path(
        "scraper/api/jobs/<uuid:job_id>/runs/<uuid:run_id>/<slug:action>/",
        views.RunActionAPI.as_view(),
        name="api_run_action",
    ),
    path(
        "scraper/jobs/<uuid:job_id>/runs/<uuid:run_id>/exports/<uuid:export_id>/download/",
        views.export_download,
        name="export_download",
    ),
]
