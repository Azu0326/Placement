from django.urls import include, path

from config.health import healthz

# django.contrib.admin is not installed: /admin/ is deliberately absent and the
# product administration interface is the custom dashboard below.
urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("", include("authentication.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("frontend_demo.urls")),
]

# Authorisation failures render the Scrapos 403 page rather than Django's.
handler403 = "dashboard.views.permission_denied_view"
