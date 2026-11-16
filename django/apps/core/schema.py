"""The database schema Django owns: its creation and Row Level Security.

Django connects as the table owner, which bypasses RLS, so the app itself is
unaffected. Enabling RLS *without policies* means every other role (notably
Supabase's `anon` / `authenticated` API roles) is denied by default, even if
the schema were ever exposed through a data API by mistake. On a plain
PostgreSQL it protects against nothing in particular and costs nothing.

Plain functions; `apps.core.signals` runs them around every `migrate`.
"""

from django.conf import settings
from django.db import connections

TABLES_WITHOUT_RLS_SQL = """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s
      AND c.relkind IN ('r', 'p')
      AND NOT c.relrowsecurity
    ORDER BY c.relname
"""


def tables_without_rls(using: str = "default") -> list[str]:
    """Names of the tables in the Django schema that do not have RLS enabled."""
    with connections[using].cursor() as cursor:
        cursor.execute(TABLES_WITHOUT_RLS_SQL, [settings.DB_SCHEMA])
        return [row[0] for row in cursor.fetchall()]


def ensure_schema(using: str = "default") -> bool:
    """Create the Django schema if it is missing; True when it was created.

    On Supabase the schema already exists (supabase/migrations) and the app
    role may not create schemas, so only create it when absent — the case for
    the throwaway pytest database and for a self-hosted database on first start.
    """
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [settings.DB_SCHEMA])
        if cursor.fetchone() is not None:
            return False
        cursor.execute(f"CREATE SCHEMA {connection.ops.quote_name(settings.DB_SCHEMA)}")
        return True


def enable_rls(using: str = "default") -> list[str]:
    """Enable RLS on every table of the Django schema lacking it; their names."""
    connection = connections[using]
    schema = connection.ops.quote_name(settings.DB_SCHEMA)
    tables = tables_without_rls(using)
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(
                f"ALTER TABLE {schema}.{connection.ops.quote_name(table)} ENABLE ROW LEVEL SECURITY"
            )
    return tables
