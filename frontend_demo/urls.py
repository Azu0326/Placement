from django.urls import path

from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("scraper/jobs/", views.JobsView.as_view(), name="jobs"),
    path("scraper/jobs/new/", views.JobNewView.as_view(), name="job_new"),
    path(
        "scraper/jobs/<slug:job_id>/",
        views.JobDetailView.as_view(),
        name="job_detail",
    ),
    path("scraper/execution/", views.ExecutionView.as_view(), name="execution"),
    path("studio/scraped/", views.ScrapedView.as_view(), name="scraped"),
    path("studio/content/", views.ContentListView.as_view(), name="content_list"),
    path(
        "studio/content/<slug:pk>/",
        views.ContentEditorView.as_view(),
        name="content_editor",
    ),
    path("studio/genai/", views.GenAIView.as_view(), name="genai"),
    path("poster/schedule/", views.ScheduleView.as_view(), name="schedule"),
    path("poster/calendar/", views.CalendarView.as_view(), name="calendar"),
    path("repository/assets/", views.AssetsView.as_view(), name="assets"),
    path(
        "repository/assets/register/",
        views.AssetRegisterView.as_view(),
        name="asset_register",
    ),
    path("repository/channels/", views.ChannelsView.as_view(), name="channels"),
    path(
        "repository/channels/new/",
        views.ChannelNewView.as_view(),
        name="channel_new",
    ),
    path("integrations/", views.IntegrationsView.as_view(), name="integrations"),
    path("design/states/", views.StatesView.as_view(), name="states"),
]
