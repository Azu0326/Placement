from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardHomeView.as_view(), name="home"),
    path("users/", views.UserListView.as_view(), name="users"),
    path("users/new/", views.UserCreateView.as_view(), name="user_new"),
    path("users/<str:username>/", views.UserDetailView.as_view(), name="user_detail"),
    # State-changing operations are POST-only; see dashboard/views.py.
    path("users/<str:username>/action/", views.user_action, name="user_action"),
    path("groups/", views.GroupListView.as_view(), name="groups"),
    path("audit/", views.AuditListView.as_view(), name="audit"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
]
