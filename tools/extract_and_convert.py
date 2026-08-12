"""Extract prototype sections and convert to Django templates (phases 5–10)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "design" / "dnc-content-platform.html"
EXTRACT = ROOT / "tools" / "_extract"
TEMPLATES = ROOT / "templates"

SECTION_MAP = {
    "s-dashboard": ("dashboard.html", "Dashboard"),
    "s-execution": ("scraper/execution.html", "Execution monitor"),
    "s-detail": ("scraper/job_detail.html", "Job detail"),
    "s-scraped": ("studio/scraped.html", "Scraped content"),
    "s-content": ("studio/content_list.html", "Content"),
    "s-editor": ("studio/editor.html", "Editor"),
    "s-genai": ("studio/genai.html", "GenAI content"),
    "s-schedule": ("poster/schedule.html", "Scheduled posts"),
    "s-calendar": ("poster/calendar.html", "Calendar"),
    "s-assets": ("repository/assets.html", "Assets"),
    "s-register": ("repository/register.html", "Register Asset"),
    "s-channels": ("repository/channels.html", "Channels"),
    "s-newchannel": ("repository/channel_new.html", "Add channel"),
    "s-integrations": ("integrations/dashboard.html", "Integrations"),
    "s-states": ("design/states.html", "States gallery"),
}

GO_URL = {
    "dashboard": "{% url 'dashboard' %}",
    "jobs": "{% url 'jobs' %}",
    "newjob": "{% url 'job_new' %}",
    "execution": "{% url 'execution' %}",
    "detail": "{% url 'job_detail' 'SC-1284' %}",
    "scraped": "{% url 'scraped' %}",
    "content": "{% url 'content_list' %}",
    "editor": "{% url 'content_editor' 'CT-904' %}",
    "genai": "{% url 'genai' %}",
    "schedule": "{% url 'schedule' %}",
    "calendar": "{% url 'calendar' %}",
    "assets": "{% url 'assets' %}",
    "register": "{% url 'asset_register' %}",
    "channels": "{% url 'channels' %}",
    "newchannel": "{% url 'channel_new' %}",
    "integrations": "{% url 'integrations' %}",
    "states": "{% url 'states' %}",
}


def extract_sections(html: str) -> None:
    EXTRACT.mkdir(parents=True, exist_ok=True)
    for sid in SECTION_MAP:
        m = re.search(
            rf'<section class="scr[^"]*" id="{sid}">(.*?)</section>',
            html,
            re.S,
        )
        if not m:
            print("MISS", sid)
            continue
        (EXTRACT / f"{sid}.html").write_text(m.group(1).strip() + "\n", encoding="utf-8")
        print("extract", sid)


def convert_body(body: str) -> str:
    # tab(group, idx, this)
    body = re.sub(
        r"onclick=\"tab\('([^']+)',\s*(\d+),\s*this\)\"",
        r'data-action="tab" data-group="\1" data-idx="\2"',
        body,
    )
    # tog('id') — optionally after event.stopPropagation();
    body = re.sub(
        r"onclick=\"(?:event\.stopPropagation\(\);)?tog\('([^']+)'\)\"",
        r'data-action="toggle" data-target="\1" onclick="event.stopPropagation()"',
        body,
    )
    body = body.replace('onclick="openDrawer()"', 'data-action="open-drawer"')
    body = body.replace('onclick="closeDrawer()"', 'data-action="close-drawer"')

    def repl_go_href(match: re.Match) -> str:
        return f'href="{GO_URL.get(match.group(1), "#")}"'

    body = re.sub(
        r'href="#"\s+onclick="go\(\'([^\']+)\',[^\"]*\)"',
        repl_go_href,
        body,
    )
    body = re.sub(
        r"onclick=\"go\('([^']+)',[^\"]*\)\"",
        lambda m: f"onclick=\"window.location='{GO_URL.get(m.group(1), '#')}'\"",
        body,
    )
    return body

def wrap_template(body: str) -> str:
    return (
        "{% extends \"base.html\" %}\n\n"
        "{% block content %}\n"
        f"{body.rstrip()}\n"
        "{% endblock %}\n"
    )


def convert_all() -> None:
    html = PROTO.read_text(encoding="utf-8")
    extract_sections(html)

    # drawer
    dm = re.search(
        r'(<div id="drawerScrim".*?</aside>)',
        html,
        re.S,
    )
    if dm:
        drawer = convert_body(dm.group(1))
        (EXTRACT / "drawer.html").write_text(drawer + "\n", encoding="utf-8")
        (TEMPLATES / "partials" / "_drawer.html").write_text(drawer + "\n", encoding="utf-8")
        print("drawer written")

    # Keep jobs/job_new (phase 4) untouched
    skip = {"s-jobs", "s-newjob"}
    for sid, (rel, _title) in SECTION_MAP.items():
        if sid in skip:
            continue
        src = EXTRACT / f"{sid}.html"
        if not src.exists():
            print("no extract", sid)
            continue
        body = convert_body(src.read_text(encoding="utf-8"))
        # detail page: inject dynamic job bits lightly
        if sid == "s-detail":
            body = body.replace("#SC-1284", "#{{ job.id }}")
            body = body.replace(
                'search.studyaustralia.gov.au/courses',
                "{{ job.url }}",
                1,
            )
        dest = TEMPLATES / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(wrap_template(body), encoding="utf-8")
        print("template", rel)


if __name__ == "__main__":
    convert_all()
