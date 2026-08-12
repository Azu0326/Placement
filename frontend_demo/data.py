"""
Central demo data for frontend TemplateView stubs.

Later screen phases pull rows from here instead of hardcoding placeholders
into templates. No models, scrapers, or AI calls.
"""

DEMO_USER = {
    "name": "Admin",
    "email": "admin@dncouncil.org",
    "initials": "A",
}

DASHBOARD_KPIS = [
    {
        "label": "Jobs today",
        "value": "48",
        "delta": "+12%",
        "tone": "ok",
        "icon": "globe",
    },
    {
        "label": "Success rate",
        "value": "91.6%",
        "delta": None,
        "tone": "ok",
        "icon": "circle-check-big",
        "bar": True,
    },
    {
        "label": "Content items",
        "value": "1,842",
        "delta": "+284",
        "tone": "accent",
        "icon": "file-text",
    },
    {
        "label": "Scheduled posts",
        "value": "26",
        "delta": None,
        "tone": "queued",
        "icon": "calendar-clock",
    },
]

JOBS = [
    {
        "id": "SC-1284",
        "url": "search.studyaustralia.gov.au/courses",
        "page": 10,
        "status": "COMPLETED",
        "attempts": 1,
        "created": "Aug 12, 2026 02:52",
        "created_time": "02:52:04",
        "completed_time": "02:52:12",
        "duration": "8.4 sec",
        "time_short": "02:52",
        "message": None,
        "recent_label": "2 minutes ago",
    },
    {
        "id": "SC-1283",
        "url": "search.studyaustralia.gov.au/courses",
        "page": 1,
        "status": "COMPLETED",
        "attempts": 1,
        "created": "Aug 12, 2026 02:41",
        "duration": "6.1 sec",
        "time_short": "02:41",
        "message": None,
        "recent_label": "14 minutes ago",
    },
    {
        "id": "SC-1282",
        "url": "search.studyaustralia.gov.au/scholarships",
        "page": 2,
        "status": "FAILED",
        "attempts": 3,
        "created": "Aug 12, 2026 02:19",
        "duration": None,
        "time_short": "02:19",
        "message": "Worker did not complete in time",
        "recent_label": "33 minutes ago",
    },
    {
        "id": "SC-1281",
        "url": "nomadlist.com/australia",
        "page": 3,
        "status": "RUNNING",
        "attempts": 1,
        "created": "Aug 12, 2026 02:04",
        "duration": "4.2 sec",
        "time_short": "02:04",
        "message": "Parsing content",
        "recent_label": "48 minutes ago",
    },
    {
        "id": "SC-1280",
        "url": "studyaustralia.gov.au/en/plan-your-studies",
        "page": 1,
        "status": "QUEUED",
        "attempts": 0,
        "created": "Aug 12, 2026 02:01",
        "duration": None,
        "time_short": "02:01",
        "message": None,
        "recent_label": "51 minutes ago",
    },
]

JOBS_LIST_META = {
    "showing_from": 1,
    "showing_to": 20,
    "total": "1,284",
    "page": 1,
    "page_count": 65,
}

RECENT_TARGETS = [
    {
        "url": "search.studyaustralia.gov.au/courses",
        "page": 10,
        "when": "2 minutes ago",
    },
    {
        "url": "search.studyaustralia.gov.au/scholarships",
        "page": 2,
        "when": "33 minutes ago",
    },
    {
        "url": "nomadlist.com/australia",
        "page": 3,
        "when": "48 minutes ago",
    },
]

CONTENT_ITEMS = [
    {
        "id": "CT-904",
        "title": "Studying in Australia: a 2026 guide for international students",
        "status": "DRAFT",
        "updated": "Aug 11, 2026",
    },
    {
        "id": "CT-903",
        "title": "Scholarship pathways for postgraduate applicants",
        "status": "IN_REVIEW",
        "updated": "Aug 10, 2026",
    },
    {
        "id": "CT-902",
        "title": "Campus living costs — Melbourne vs Sydney",
        "status": "APPROVED",
        "updated": "Aug 9, 2026",
    },
]

ASSETS = [
    {
        "id": "AS-220",
        "name": "hero-melbourne-skyline.jpg",
        "kind": "image",
        "size": "1.8 MB",
    },
    {
        "id": "AS-219",
        "name": "visa-checklist-2026.pdf",
        "kind": "document",
        "size": "420 KB",
    },
]

CHANNELS = [
    {
        "id": "CH-12",
        "name": "DNC LinkedIn",
        "platform": "LinkedIn",
        "status": "Active",
    },
    {
        "id": "CH-11",
        "name": "Study AU Instagram",
        "platform": "Instagram",
        "status": "Needs attention",
    },
]

SCHEDULED_POSTS = [
    {
        "id": "PS-77",
        "title": "February intake reminders",
        "channel": "DNC LinkedIn",
        "when": "Aug 14, 2026 09:00",
        "status": "Scheduled",
    },
    {
        "id": "PS-76",
        "title": "Scholarship roundup",
        "channel": "Study AU Instagram",
        "when": "Aug 13, 2026 18:30",
        "status": "FAILED",
    },
]


def get_job(job_id: str):
    needle = job_id.lstrip("#")
    for job in JOBS:
        if job["id"] == needle:
            return job
    return JOBS[0]


def get_content(content_id: str):
    for item in CONTENT_ITEMS:
        if item["id"] == content_id:
            return item
    return CONTENT_ITEMS[0]
