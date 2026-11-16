-- Baseline for the Django backend on Supabase.
--
-- 1. `partitario_app`: the only role Django connects as. It owns the `partitario`
--    schema and nothing else, instead of using the all-powerful `postgres`.
-- 2. `partitario` schema: every Django table lives here, NOT in `public`, so it
--    is never exposed through the Supabase Data API (PostgREST only serves the
--    schemas listed in config.toml -> [api].schemas).
-- 3. Private storage bucket for uploaded documents.
--
-- RLS on the Django tables themselves is enabled by Django after every
-- `migrate` (see apps/core/schema.py) because the tables are created by Django.

-- 1. Application role -----------------------------------------------------------
-- Created WITHOUT a password, so it cannot log in until one is set out of band
-- (a password must never be committed):
--   local   supabase/seed.sql sets a public dev password
--   hosted  run once in the SQL editor:
--             alter role partitario_app with password '<strong password>';
do $$
begin
    if not exists (select from pg_roles where rolname = 'partitario_app') then
        create role partitario_app with login noinherit nocreatedb nocreaterole;
    end if;
end
$$;

-- Lets the migration role create objects on behalf of partitario_app below.
grant partitario_app to current_user;

-- Tables resolve to the app schema even without the search_path startup option.
alter role partitario_app set search_path = partitario;

-- 2. Schema ---------------------------------------------------------------------
create schema if not exists partitario authorization partitario_app;

-- Defence in depth: the API roles get nothing in this schema, now or later.
revoke all on schema partitario from public, anon, authenticated, service_role;
alter default privileges for role partitario_app in schema partitario
    revoke all on tables from public, anon, authenticated, service_role;
alter default privileges for role partitario_app in schema partitario
    revoke all on sequences from public, anon, authenticated, service_role;
alter default privileges for role partitario_app in schema partitario
    revoke all on functions from public, anon, authenticated, service_role;

-- 3. Storage --------------------------------------------------------------------
-- Private bucket. storage.objects has RLS enabled by Supabase and we add NO
-- policies: only the S3 access keys (i.e. Django) can read or write. Files are
-- served to the browser through short-lived signed URLs.
insert into storage.buckets (id, name, public, file_size_limit)
values ('documents', 'documents', false, 20971520)
on conflict (id) do update
    set public = false,
        file_size_limit = excluded.file_size_limit;
