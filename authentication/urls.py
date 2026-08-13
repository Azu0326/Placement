from django.urls import path

from . import views

app_name = "authentication"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # Hosted-UI single sign-on, alongside the Scrapos password form.
    path("auth/login/", views.oauth_start, name="oauth_start"),
    # Straight to one social provider, mirroring the member portal's
    # /auth/social/<provider>/ route. One callback serves them all.
    path("auth/social/<slug:provider>/", views.oauth_start, name="oauth_social"),
    path("auth/callback/", views.oauth_callback, name="oauth_callback"),
]
