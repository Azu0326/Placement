from django.urls import path

from . import views

app_name = "authentication"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # Hosted-UI single sign-on, alongside the Scrapos password form.
    path("auth/login/", views.oauth_start, name="oauth_start"),
    path("auth/callback/", views.oauth_callback, name="oauth_callback"),
]
