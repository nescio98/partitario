"""Receivers of the migration signals, connected in `CoreConfig.ready`.

They are connected with `sender=<the core app>`, so each runs once per
`migrate` (the signals are otherwise sent once for every installed app).
"""

from django.apps import AppConfig
from django.core.management import call_command

from . import schema


def create_schema(sender: AppConfig, using: str, **kwargs: object) -> None:
    """pre_migrate: the schema must exist before the first table is created."""
    schema.ensure_schema(using)


def create_cache_table(sender: AppConfig, using: str, **kwargs: object) -> None:
    """post_migrate: the table of the database cache, if that is the cache in use.

    `createcachetable` only creates what is missing, and nothing at all when
    the cache is Redis. Connected before `protect_tables`, so the table gets
    RLS like every other.
    """
    call_command("createcachetable", database=using, verbosity=0)


def protect_tables(sender: AppConfig, using: str, **kwargs: object) -> None:
    """post_migrate: no table Django just created is left without RLS."""
    schema.enable_rls(using)
