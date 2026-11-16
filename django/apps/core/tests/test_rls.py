import pytest
from django.db import connection

from apps.core.schema import ensure_schema, tables_without_rls


@pytest.mark.django_db
def test_every_django_table_has_rls_enabled():
    """Guard rail: a new model must never ship without RLS."""
    assert tables_without_rls() == []


@pytest.mark.django_db
def test_tables_live_in_the_app_schema(settings):
    with connection.cursor() as cursor:
        cursor.execute("SELECT schemaname FROM pg_tables WHERE tablename = 'accounts_user'")
        assert [row[0] for row in cursor.fetchall()] == [settings.DB_SCHEMA]


@pytest.mark.django_db
def test_existing_schema_is_left_alone():
    assert ensure_schema() is False
