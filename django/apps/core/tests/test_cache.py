"""The cache is one store shared by every process, created by `migrate`."""

import pytest
from django.conf import settings
from django.core.cache import cache, caches
from django.db import connection

from apps.core import diagnostics
from apps.core.schema import tables_without_rls


def test_the_default_cache_is_the_database():
    assert str(settings.CACHES["default"]["BACKEND"]).endswith("DatabaseCache")


@pytest.mark.django_db
def test_migrate_creates_the_cache_table_with_rls():
    assert settings.CACHE_TABLE in connection.introspection.table_names()
    assert settings.CACHE_TABLE not in tables_without_rls()


@pytest.mark.django_db
def test_a_value_survives_a_fresh_connection_to_the_cache():
    # What a private per-process memory cache cannot do: a second handle,
    # like another gunicorn worker would hold, sees the same value.
    cache.set("shared", "value", timeout=30)
    assert caches.create_connection("default").get("shared") == "value"


@pytest.mark.django_db
def test_check_services_covers_the_cache():
    result = diagnostics.check_cache()
    assert result.problems == []
    assert "DatabaseCache set/get/delete OK" in result.summary
