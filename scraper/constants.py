"""Shared vocabulary for scraper jobs, runs and exports.

User-facing run status is mapped to the product vocabulary
QUEUED / RUNNING / COMPLETED / FAILED. Internal statuses stay more granular
so pause, cancel and partial completion can be persisted safely.
"""

from __future__ import annotations

JOB_STATUS_DRAFT = "draft"
JOB_STATUS_ACTIVE = "active"
JOB_STATUS_ARCHIVED = "archived"
JOB_STATUS_CHOICES = [
    (JOB_STATUS_DRAFT, "Draft"),
    (JOB_STATUS_ACTIVE, "Active"),
    (JOB_STATUS_ARCHIVED, "Archived"),
]

HTTP_GET = "GET"
HTTP_POST = "POST"
HTTP_METHOD_CHOICES = [
    (HTTP_GET, "GET"),
    (HTTP_POST, "POST"),
]

RENDER_AUTO = "auto"
RENDER_HTTP = "http"
RENDER_BROWSER = "browser"
RENDER_MODE_CHOICES = [
    (RENDER_AUTO, "Auto"),
    (RENDER_HTTP, "HTTP"),
    (RENDER_BROWSER, "Browser"),
]

SOURCE_URL_QUERY = "url_query"
SOURCE_URL_PATH = "url_path"
SOURCE_COUNTER = "counter"
SOURCE_FIXED = "fixed"
SOURCE_LIST = "list"
SOURCE_HTML_ELEMENT = "html_element"
SOURCE_HTML_ATTRIBUTE = "html_attribute"
SOURCE_REGEX = "regex"
SOURCE_PAGE_NUMBER = "page_number"
SOURCE_REQUEST_URL = "request_url"
SOURCE_PARENT_RECORD = "parent_record"
SOURCE_SYSTEM = "system"
SOURCE_RUN_TIMESTAMP = "run_timestamp"
SOURCE_TYPE_CHOICES = [
    (SOURCE_URL_QUERY, "URL query parameter"),
    (SOURCE_URL_PATH, "URL path segment"),
    (SOURCE_COUNTER, "Counter"),
    (SOURCE_FIXED, "Fixed value"),
    (SOURCE_LIST, "List of values"),
    (SOURCE_HTML_ELEMENT, "HTML element"),
    (SOURCE_HTML_ATTRIBUTE, "HTML attribute"),
    (SOURCE_REGEX, "Regular-expression result"),
    (SOURCE_PAGE_NUMBER, "Current page number"),
    (SOURCE_REQUEST_URL, "Current request URL"),
    (SOURCE_PARENT_RECORD, "Parent-record value"),
    (SOURCE_SYSTEM, "System-generated value"),
    (SOURCE_RUN_TIMESTAMP, "Run timestamp"),
]

SCOPE_RESULT_PAGE = "result_page"
SCOPE_RESULT_ITEM = "result_item"
SCOPE_DETAIL_PAGE = "detail_page"
SCOPE_VARIABLE = "variable"
SCOPE_SYSTEM = "system"
SCOPE_CHOICES = [
    (SCOPE_RESULT_PAGE, "Result page"),
    (SCOPE_RESULT_ITEM, "Result item"),
    (SCOPE_DETAIL_PAGE, "Detail page"),
    (SCOPE_VARIABLE, "Variable"),
    (SCOPE_SYSTEM, "System"),
]

VALUE_TEXT = "text_content"
VALUE_INNER_HTML = "inner_html"
VALUE_ATTRIBUTE = "attribute"
VALUE_EXISTS = "existence"
VALUE_FROM_CHOICES = [
    (VALUE_TEXT, "Text content"),
    (VALUE_INNER_HTML, "Inner HTML"),
    (VALUE_ATTRIBUTE, "Attribute"),
    (VALUE_EXISTS, "Element existence"),
]

DATA_TEXT = "text"
DATA_LONG_TEXT = "long_text"
DATA_INTEGER = "integer"
DATA_DECIMAL = "decimal"
DATA_BOOLEAN = "boolean"
DATA_DATE = "date"
DATA_DATETIME = "datetime"
DATA_CURRENCY = "currency"
DATA_URL = "url"
DATA_EMAIL = "email"
DATA_HTML = "html"
DATA_JSON = "json"
DATA_LIST = "list"
DATA_TYPE_CHOICES = [
    (DATA_TEXT, "Text"),
    (DATA_LONG_TEXT, "Long text"),
    (DATA_INTEGER, "Integer"),
    (DATA_DECIMAL, "Decimal"),
    (DATA_BOOLEAN, "Boolean"),
    (DATA_DATE, "Date"),
    (DATA_DATETIME, "Date and time"),
    (DATA_CURRENCY, "Currency"),
    (DATA_URL, "URL"),
    (DATA_EMAIL, "Email"),
    (DATA_HTML, "HTML"),
    (DATA_JSON, "JSON"),
    (DATA_LIST, "List"),
]

PAGINATION_QUERY = "query_parameter"
PAGINATION_TEMPLATE = "url_template"
PAGINATION_NEXT = "next_button"
PAGINATION_LOAD_MORE = "load_more"
PAGINATION_INFINITE = "infinite_scroll"
PAGINATION_EXTRACTED = "extracted_url"
PAGINATION_NONE = "none"
PAGINATION_MODE_CHOICES = [
    (PAGINATION_QUERY, "URL query parameter"),
    (PAGINATION_TEMPLATE, "URL template counter"),
    (PAGINATION_NEXT, "Next-button link"),
    (PAGINATION_LOAD_MORE, "Load More button"),
    (PAGINATION_INFINITE, "Infinite scroll"),
    (PAGINATION_EXTRACTED, "Extracted next-page URL"),
    (PAGINATION_NONE, "No pagination"),
]

DUPLICATE_SKIP = "skip"
DUPLICATE_UPDATE = "update"
DUPLICATE_KEEP = "keep"
DUPLICATE_HANDLING_CHOICES = [
    (DUPLICATE_SKIP, "Skip"),
    (DUPLICATE_UPDATE, "Update existing record"),
    (DUPLICATE_KEEP, "Keep duplicate"),
]

RUN_QUEUED = "queued"
RUN_PREPARING = "preparing"
RUN_RUNNING = "running"
RUN_PAUSING = "pausing"
RUN_PAUSED = "paused"
RUN_CANCELLING = "cancelling"
RUN_CANCELLED = "cancelled"
RUN_COMPLETED = "completed"
RUN_COMPLETED_WITH_ERRORS = "completed_with_errors"
RUN_FAILED = "failed"
RUN_STATUS_CHOICES = [
    (RUN_QUEUED, "Queued"),
    (RUN_PREPARING, "Preparing"),
    (RUN_RUNNING, "Running"),
    (RUN_PAUSING, "Pausing"),
    (RUN_PAUSED, "Paused"),
    (RUN_CANCELLING, "Cancelling"),
    (RUN_CANCELLED, "Cancelled"),
    (RUN_COMPLETED, "Completed"),
    (RUN_COMPLETED_WITH_ERRORS, "Completed with errors"),
    (RUN_FAILED, "Failed"),
]

# Product-facing status vocabulary from .cursorrules / design-tokens.md.
# Pause/cancel are shown as their own labels because the feature requires them.
DISPLAY_QUEUED = "QUEUED"
DISPLAY_RUNNING = "RUNNING"
DISPLAY_COMPLETED = "COMPLETED"
DISPLAY_FAILED = "FAILED"
DISPLAY_PAUSED = "PAUSED"
DISPLAY_CANCELLED = "CANCELLED"

RUN_DISPLAY_STATUS = {
    RUN_QUEUED: DISPLAY_QUEUED,
    RUN_PREPARING: DISPLAY_RUNNING,
    RUN_RUNNING: DISPLAY_RUNNING,
    RUN_PAUSING: DISPLAY_RUNNING,
    RUN_CANCELLING: DISPLAY_RUNNING,
    RUN_PAUSED: DISPLAY_PAUSED,
    RUN_CANCELLED: DISPLAY_CANCELLED,
    RUN_COMPLETED: DISPLAY_COMPLETED,
    RUN_COMPLETED_WITH_ERRORS: DISPLAY_COMPLETED,
    RUN_FAILED: DISPLAY_FAILED,
}

ACTIVE_RUN_STATUSES = frozenset(
    {
        RUN_QUEUED,
        RUN_PREPARING,
        RUN_RUNNING,
        RUN_PAUSING,
        RUN_CANCELLING,
    }
)
STOP_REQUESTED_STATUSES = frozenset({RUN_PAUSING, RUN_CANCELLING, RUN_PAUSED, RUN_CANCELLED})
TERMINAL_RUN_STATUSES = frozenset(
    {RUN_PAUSED, RUN_CANCELLED, RUN_COMPLETED, RUN_COMPLETED_WITH_ERRORS, RUN_FAILED}
)

PHASE_PREPARING = "preparing"
PHASE_LISTING = "listing"
PHASE_DETAIL = "detail"
PHASE_VALIDATING = "validating"
PHASE_FINALISING = "finalising"
PHASE_EXPORTING = "exporting"

RECORD_VALID = "valid"
RECORD_INVALID = "invalid"
RECORD_PARTIAL = "partial"
RECORD_FAILED = "failed"
RECORD_STATUS_CHOICES = [
    (RECORD_VALID, "Valid"),
    (RECORD_INVALID, "Invalid"),
    (RECORD_PARTIAL, "Partial"),
    (RECORD_FAILED, "Failed"),
]

EXPORT_CSV = "csv"
EXPORT_SQLITE = "sqlite"
EXPORT_FORMAT_CHOICES = [
    (EXPORT_CSV, "CSV"),
    (EXPORT_SQLITE, "SQLite"),
]

EXPORT_PENDING = "pending"
EXPORT_RUNNING = "running"
EXPORT_READY = "ready"
EXPORT_FAILED = "failed"
EXPORT_EXPIRED = "expired"
EXPORT_STATUS_CHOICES = [
    (EXPORT_PENDING, "Pending"),
    (EXPORT_RUNNING, "Running"),
    (EXPORT_READY, "Ready"),
    (EXPORT_FAILED, "Failed"),
    (EXPORT_EXPIRED, "Expired"),
]

EXPORT_SCOPE_ALL = "all"
EXPORT_SCOPE_VALID = "valid"
EXPORT_SCOPE_FILTERED = "filtered"

EVENT_INFO = "info"
EVENT_WARNING = "warning"
EVENT_ERROR = "error"
EVENT_LEVEL_CHOICES = [
    (EVENT_INFO, "Info"),
    (EVENT_WARNING, "Warning"),
    (EVENT_ERROR, "Error"),
]

FIELD_NAME_RE = r"^[a-z][a-z0-9_]*$"
RESERVED_FIELD_NAMES = frozenset(
    {
        "id",
        "pk",
        "job",
        "run",
        "owner",
        "class",
        "def",
        "import",
        "export",
        "type",
        "model",
        "status",
        "created",
        "updated",
        "password",
        "secret",
        "token",
        "cookie",
        "authorization",
    }
)
SYSTEM_EXPORT_COLUMNS = (
    "_record_id",
    "_source_url",
    "_source_page",
    "_scraped_at",
    "_validation_status",
)

STOP_NO_RESULT_ITEMS = "no_result_items"
STOP_NO_NEW_UNIQUE = "no_new_unique_records"
STOP_NO_NEW_DETAIL_URLS = "no_new_detail_urls"
STOP_NEXT_MISSING = "next_button_missing"
STOP_NEXT_DISABLED = "next_button_disabled"
STOP_REPEATED_PAGE = "repeated_page"
STOP_REPEATED_NEXT_URL = "repeated_next_url"
STOP_MAX_PAGES = "maximum_pages_reached"
STOP_MAX_RECORDS = "maximum_records_reached"
STOP_EMPTY_PAGES = "consecutive_empty_pages"
STOP_REQUEST_FAILURES = "consecutive_request_failures"
STOP_USER_CANCEL = "user_cancellation"
STOP_MAX_RUNTIME = "maximum_runtime_reached"

DEFAULT_STOP_CONDITIONS = [
    STOP_NO_RESULT_ITEMS,
    STOP_NO_NEW_DETAIL_URLS,
    STOP_REPEATED_PAGE,
    STOP_MAX_PAGES,
    STOP_MAX_RECORDS,
    STOP_EMPTY_PAGES,
    STOP_REQUEST_FAILURES,
    STOP_USER_CANCEL,
]

WIZARD_STEPS = [
    ("basic", "Basic Information"),
    ("source", "Source and Request"),
    ("variables", "Variable Parameters"),
    ("results", "Result Selection"),
    ("detail", "Detail Page Fields"),
    ("pagination", "Pagination"),
    ("execution", "Execution Settings"),
    ("preview", "Test and Preview"),
    ("review", "Review and Save"),
]

ORIGIN_MANUAL = "manual"
ORIGIN_CSV = "csv"
ORIGIN_CHOICES = [
    (ORIGIN_MANUAL, "Manual"),
    (ORIGIN_CSV, "CSV import"),
]

CSV_ROW_VARIABLE = "VARIABLE"
CSV_ROW_RESULT_SELECTION = "RESULT_SELECTION"
CSV_ROW_RESULT_FIELD = "RESULT_FIELD"
CSV_ROW_DETAIL_FIELD = "DETAIL_FIELD"
CSV_ROW_TYPES = frozenset(
    {CSV_ROW_VARIABLE, CSV_ROW_RESULT_SELECTION, CSV_ROW_RESULT_FIELD, CSV_ROW_DETAIL_FIELD}
)

CSV_HEADERS = (
    "row_type",
    "name",
    "display_label",
    "source",
    "scope",
    "selector_or_parameter",
    "value_from",
    "attribute_name",
    "data_type",
    "start_value",
    "increment",
    "fixed_value",
    "list_values",
    "default_value",
    "required",
    "multiple_values",
    "transform",
    "unique",
    "include_in_output",
    "sort_order",
    "result_selector",
    "detail_link_selector",
    "follow_detail_page",
    "pagination_mode",
    "maximum_pages",
    "maximum_records",
    "wait_for_selector",
    "enabled",
)

PLACEHOLDER_SELECTOR_TOKEN = "REPLACE_WITH_VERIFIED"

SCHEMA_VERSION = 1
SCRAPOS_VERSION = "1.0.0"

SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-csrf-token",
        "x-amz-security-token",
    }
)
