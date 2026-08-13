from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = "authentication"
    verbose_name = "Scrapos authentication"

    def ready(self):
        # Registers the deployment checks that refuse to start a production
        # container with a half-configured identity provider.
        from . import checks  # noqa: F401
