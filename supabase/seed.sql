-- LOCAL ONLY: applied by `supabase start` / `supabase db reset`, never by
-- `supabase db push`. Hosted projects get their password from the SQL editor
-- (see supabase/migrations/20261114000000_baseline.sql).

-- Public development password, the counterpart of postgres/postgres.
alter role partitario_app with password 'partitario_app';

-- pytest-django creates and drops a throwaway `test_postgres` database.
alter role partitario_app createdb;
