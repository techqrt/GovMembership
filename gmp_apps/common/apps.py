from importlib import import_module

from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gmp_apps.common'

    def ready(self) -> None:
        import_module('gmp_apps.common.checks')  # registers the deployment checks
