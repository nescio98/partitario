# Makefile guide

The `Makefile` is the single entry point for every routine task. Run it from
the repository root; `make` on its own prints every target with a one-line
description.

## How it is organised

The name prefix tells you which environment a target touches:

| Prefix | Acts on | Config file |
|---|---|---|
| none (`dev`, `migrate`, `test`, …) | this worktree and its local Supabase project | `.env` |
| `worktree-*` | the whole development stack of this worktree (Supabase project, dev server) | `.env` |
| `local-*` | the interface on this machine, the data on a hosted Supabase project (personal use) | `.env.local` |
| `staging-*` | the staging server stack and its Supabase project | `.env.staging` |
| `prod-*` | production | `.env.prod` |
| `selfhost-*` | the self-hosted stack (any Postgres, any S3 or a volume) | `.env.selfhost` |

Three things apply throughout:

- **Env files are never overwritten.** Every `*-env` target creates the file
  only if it is missing. `make env` also refreshes the keys it manages in
  `.env` (the ports of the local Supabase project, the dev port, the instance
  name) and leaves every other line alone.
- **Nothing is hard-coded.** Container names and local ports come from
  `PROJECT` and `DEV_PORT_BASE` at the top of the `Makefile` and from `.env`:
  several worktrees and projects run side by side
  ([worktrees.md](worktrees.md)).
- **Production asks first.** `prod-push`, `prod-up` and `prod-superuser` make
  you type `prod`; for scripts, pass `CONFIRM=prod`. The other `prod-*`
  targets do not ask.
- **Local targets need Supabase running** (`make supabase-start`), except
  `make test` and `make smoke`, which need Docker only.

## Scenarios

### 1. First time on a new machine

```bash
make setup
make worktree-up   # http://localhost:8100/admin/ in the primary checkout
```

`setup` chains: install the Python dependencies, install the git hooks, start
Supabase, create `.env` (with the ports Supabase was given), migrate, create
the superuser, compile the translations, and verify the backing services. To choose the admin password, run
`make supabase-start env` first and change `DJANGO_SUPERUSER_PASSWORD` in
`.env` before `make setup`: an existing user is never modified afterwards.

### 2. Daily development

```bash
make worktree-up      # start Supabase, refresh .env, start the dev server; returns when it is ready
make worktree-info    # where it is running
make worktree-logs    # follow the server log
make worktree-down    # when done: remove the dev containers, stop Supabase; data is kept
```

The dev server runs in Docker only, detached: Django plus a Tailwind watcher
on the mounted source, so a change to Python, a template or the stylesheet is
live. `worktree-up` exits with an error, and the server log, when the server
does not come up. Run it again after a change to `uv.lock` or the
translations: it rebuilds the image.

`make worktree-info` prints the address of the dev server; `supabase status`
the other local URLs and keys. After Supabase was given new ports (rare: a
`supabase stack destroy`, a renamed branch), `make env` refreshes `.env`. If
the dev port was taken by another process meanwhile, `make env-port` picks a
new one.

### 2b. Several worktrees at once

```bash
git worktree add ../wt-8 -b lab-8-demo && cd ../wt-8
make install worktree-up   # own Supabase project, .env, dev server with migrations and admin user (:8108)
make worktree-info         # instance name, application URL, database port, Supabase API URL
make worktree-logs         # follow the dev server log
make worktree-list         # every worktree: branch, URL, dev server and Supabase up or down
make supabase-list         # every local Supabase project on this machine
make worktree-down         # remove the dev containers and stop Supabase; data and ports are kept
make worktree-destroy      # DESTRUCTIVE: before `git worktree remove`
make worktree-prune        # clean up after worktrees removed without it (lists, then asks)
```

Each worktree keeps its port for as long as it exists, running or not, and
starts with the values you changed in the main checkout's `.env`. The design
is in [worktrees.md](worktrees.md).

`worktree-up` is `supabase-start env`, then the dev containers, detached; the
web one migrates and creates the admin user when it starts. `worktree-destroy` removes this
worktree's dev containers, images and stylesheet volume, its smoke images and
its local Supabase project with its data, and nothing else.

### 3. Changing models

There is no target for creating a Django migration; that runs from `django/`:

```bash
cd django && uv run manage.py makemigrations <app>
make migrate    # applies it, creates the schema if missing, enables RLS
make check      # confirms schema, RLS on every table, private storage
```

### 4. Changing interface text

```bash
make messages          # extract new strings into django/locale/it/LC_MESSAGES/django.po
# fill in the new msgstr entries
make compilemessages
```

Both need GNU gettext on the machine.

### 5. Before committing

```bash
make format       # ruff autofix and format
make lint         # ruff check, plus the app dependency direction (import-linter)
make typecheck    # mypy
make test         # pytest on a throwaway Postgres; make test ARGS="-k rls"
```

The git hooks run lint and typecheck again on commit (`make hooks` installs
them; `make setup` already did). Heavier checks, for specific changes:

| Target | When |
|---|---|
| `make hooks-run` | after touching shell scripts, the Dockerfile or the workflow (adds shellcheck, hadolint, actionlint) |
| `make smoke` | after touching `docker/`, nginx or HTTP-related settings (about a minute: builds and tests the real stack) |
| `make test-supabase` | to run the same tests on the local Supabase database |
| `make secrets` | to scan the whole git history for secrets (gitleaks, in Docker) |
| `make ci-lint` | after changing `.gitlab/.gitlab-ci.yml`: validates it against GitLab (`glab ci lint`, needs `glab auth login`) |

### 6. Changing something Supabase owns (role, schema, bucket)

```bash
supabase migration new add_something    # creates a file in supabase/migrations/
make db-reset                           # DESTRUCTIVE: wipes this worktree's local database and rebuilds it
```

`db-reset` re-applies the Supabase migrations and seed, then the Django
migrations and the superuser.

### 7. Using the application alone: local interface, cloud data

```bash
make local-env        # creates .env.local; fill it in
make local-push       # first time: role, schema and bucket (DRY=1 to preview)
make local-migrate    # first time, and after every update: the tables
make local-superuser  # first time: your login
make local-up         # http://localhost:8003/admin/ (LOCAL_PORT in .env.local)
make local-check      # schema, RLS, bucket round trip
make local-backup     # database dump into backups/
make local-down       # the data stays in the cloud
```

After `local-push`, set the role's password in the Supabase SQL editor
([deployment.md](deployment.md#preparing-a-supabase-project)). This is not the
development environment: `.env.local` points at real data, so migrations run
only when you call `local-migrate`. The server listens on `127.0.0.1` only,
with `DEBUG` on: do not expose it.

### 8. Deploying to staging, then production

One-time, per environment:

```bash
make staging-env         # creates .env.staging; fill it in
make staging-push DRY=1  # preview the Supabase migrations
make staging-push        # apply them (role, schema, bucket)
```

Then set the role's password in the Supabase SQL editor (the full list of
steps is in [deployment.md](deployment.md#preparing-a-supabase-project)).

Every deploy:

```bash
make staging-up          # build (or pull), migrate, start
make staging-superuser   # first time only; interactive
make staging-check       # schema, RLS, bucket round trip
make staging-logs
```

Production is the same with `prod-` in place of `staging-`. With
`PARTITARIO_VERSION` set in the env file, `up` pulls that published release;
with it empty, it builds from the checkout. `*-down` stops the containers and
keeps the data and the certificates.

### 9. Self-hosting

```bash
make selfhost-env        # generates the secrets; set DJANGO_ALLOWED_HOSTS and the Turnstile keys in the file
make selfhost-up
make selfhost-superuser  # first time only
make selfhost-check
make selfhost-logs
make selfhost-down       # the database and documents volumes are kept
```

Then point the machine's reverse proxy at `127.0.0.1:8080`. There is no `push`
step: Django creates its own schema. `docker/compose.override.yaml`
(gitignored) is merged in automatically when it exists.

### 10. Backups

```bash
make backup            # local database
make staging-backup
make prod-backup
make selfhost-backup   # database, plus the documents volume when stored on disk
```

All write into `backups/` (gitignored). `pg_dump` must be at least as new as
the server: for a server newer than PostgreSQL 17 pass a matching client,
e.g. `make prod-backup PG_CLIENT_IMAGE=postgres:18-alpine`.

## Variables you can pass

| Variable | Used by | Meaning |
|---|---|---|
| `ARGS` | `test`, `test-supabase` | extra pytest arguments |
| `DRY=1` | `staging-push`, `prod-push`, `local-push` | preview the Supabase migrations without applying them |
| `CONFIRM=prod` | `prod-push`, `prod-up`, `prod-superuser` | skip the interactive confirmation |
| `PG_CLIENT_IMAGE` | `*-backup` | image providing `pg_dump` |
| `GITLEAKS_IMAGE` | `secrets` | image providing gitleaks |
| `YES=1` | `worktree-prune` | skip the confirmation |
| `SUPABASE_EXCLUDE` | `supabase-start`, `setup`, `worktree-up` | Supabase services to leave out, e.g. `rest,auth,studio,mail` |
| `DEV_PORT_BASE` | `env`, `env-port` | first port of the project's block of 100 (default in the `Makefile`) |
| `SMOKE_HTTP_PORT`, `SMOKE_HTTP_TLS_PORT`, `SMOKE_HTTPS_PORT` | `smoke` | fixed ports instead of three free ones |

## What the Makefile does not do

- **Restore.** There is no restore target; a dump is restored by hand with
  `pg_restore`.
- **Release.** No make target (and, for now, no CI job) publishes images;
  see [development.md](development.md#continuous-integration-and-releases).
- **Creating Django migrations or adding dependencies.** Those are
  `uv run manage.py makemigrations` and `uv add <pkg>`, from `django/`.
- **Backing up S3 documents.** Only the on-disk `media` volume is archived.
