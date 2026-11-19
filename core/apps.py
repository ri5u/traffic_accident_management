from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Traffic & Accident Management"

    def ready(self):
        # After `migrate`, make sure the role groups and their permissions exist.
        from .roles import ensure_role_groups

        post_migrate.connect(ensure_role_groups, sender=self)
