from django.apps import AppConfig
from django.db.models.signals import post_migrate, pre_migrate


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Core"

    def ready(self) -> None:
        from . import signals

        # sender=self: once per `migrate`, not once per installed app.
        pre_migrate.connect(signals.create_schema, sender=self)
        # Receivers run in this order: the cache table exists before RLS is applied.
        post_migrate.connect(signals.create_cache_table, sender=self)
        post_migrate.connect(signals.protect_tables, sender=self)
