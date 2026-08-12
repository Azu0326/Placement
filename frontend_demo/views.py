from django.views.generic import TemplateView

from . import data


class ShellView(TemplateView):
    """TemplateView stub with shared chrome context keys."""

    nav_key = ""
    crumb = ""
    page_title = ""
    nav_group = ""

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


class DashboardView(ShellView):
    template_name = "dashboard.html"
    nav_key = "dashboard"
    crumb = "Dashboard"
    page_title = "Dashboard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["kpis"] = data.DASHBOARD_KPIS
        ctx["recent_jobs"] = data.JOBS[:4]
        return ctx


class JobsView(ShellView):
    template_name = "scraper/jobs.html"
    nav_key = "jobs"
    nav_group = "g-scraper"
    crumb = "Scraper / Jobs"
    page_title = "Scrape jobs"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["jobs"] = data.JOBS
        ctx["jobs_meta"] = data.JOBS_LIST_META
        ctx["show_queued_toast"] = self.request.GET.get("queued") == "1"
        return ctx


class JobNewView(ShellView):
    template_name = "scraper/job_new.html"
    nav_key = "newjob"
    nav_group = "g-scraper"
    crumb = "Scraper / Jobs / New job"
    page_title = "New scrape job"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["recent_targets"] = data.RECENT_TARGETS
        return ctx


class ExecutionView(ShellView):
    template_name = "scraper/execution.html"
    nav_key = "execution"
    nav_group = "g-scraper"
    crumb = "Scraper / Execution"
    page_title = "Execution monitor"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["jobs"] = data.JOBS
        return ctx


class JobDetailView(ShellView):
    template_name = "scraper/job_detail.html"
    nav_key = "detail"
    nav_group = "g-scraper"
    page_title = "Job detail"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = data.get_job(kwargs["job_id"])
        ctx["job"] = job
        ctx["crumb"] = f"Scraper / Jobs / #{job['id']}"
        return ctx


class ScrapedView(ShellView):
    template_name = "studio/scraped.html"
    nav_key = "scraped"
    nav_group = "g-studio"
    crumb = "Content Studio / Scraped"
    page_title = "Scraped content"


class ContentListView(ShellView):
    template_name = "studio/content_list.html"
    nav_key = "content"
    nav_group = "g-studio"
    crumb = "Content Studio / Content"
    page_title = "Content"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["content_items"] = data.CONTENT_ITEMS
        return ctx


class ContentEditorView(ShellView):
    template_name = "studio/editor.html"
    nav_key = "editor"
    nav_group = "g-studio"
    crumb = "Content Studio / Content / Editor"
    page_title = "Editor"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["item"] = data.get_content(kwargs.get("pk", ""))
        return ctx


class GenAIView(ShellView):
    template_name = "studio/genai.html"
    nav_key = "genai"
    nav_group = "g-studio"
    crumb = "Content Studio / GenAI Content"
    page_title = "GenAI content"


class ScheduleView(ShellView):
    template_name = "poster/schedule.html"
    nav_key = "schedule"
    nav_group = "g-poster"
    crumb = "Poster / Schedule"
    page_title = "Scheduled posts"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["posts"] = data.SCHEDULED_POSTS
        return ctx


class CalendarView(ShellView):
    template_name = "poster/calendar.html"
    nav_key = "calendar"
    nav_group = "g-poster"
    crumb = "Poster / Calendar"
    page_title = "Calendar"


class AssetsView(ShellView):
    template_name = "repository/assets.html"
    nav_key = "assets"
    nav_group = "g-assets"
    crumb = "Repository / Assets"
    page_title = "Assets"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["assets"] = data.ASSETS
        return ctx


class AssetRegisterView(ShellView):
    template_name = "repository/register.html"
    nav_key = "register"
    nav_group = "g-assets"
    crumb = "Repository / Register Asset"
    page_title = "Register Asset"


class ChannelsView(ShellView):
    template_name = "repository/channels.html"
    nav_key = "channels"
    nav_group = "g-assets"
    crumb = "Repository / Channels"
    page_title = "Channels"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["channels"] = data.CHANNELS
        return ctx


class ChannelNewView(ShellView):
    template_name = "repository/channel_new.html"
    nav_key = "newchannel"
    nav_group = "g-assets"
    crumb = "Repository / Channels / Add channel"
    page_title = "Add channel"


class IntegrationsView(ShellView):
    template_name = "integrations/dashboard.html"
    nav_key = "integrations"
    nav_group = "g-integ"
    crumb = "Integrations / Dashboard"
    page_title = "Integrations"


class StatesView(ShellView):
    template_name = "design/states.html"
    nav_key = "states"
    crumb = "Design / States"
    page_title = "States gallery"
