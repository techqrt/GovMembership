from importlib import import_module

from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gmp_apps.authentication'

    def ready(self) -> None:
        import_module('gmp_apps.authentication.jwt')  # registers the swagger auth extension
