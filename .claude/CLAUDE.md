# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

A single-user Django webapp that replaces `PartitaIva2026.xlsx`: the ledger of an
Italian partita IVA in **regime forfettario** plus its bank and securities
accounts.

It runs on PostgreSQL plus a private document store (S3-compatible bucket or
a local volume). dev, staging and prod get both from Supabase (CLI,
migrations, local stack); selfhost brings its own Postgres and volume, or uses
any Postgres and any S3 service.

**Current state: infrastructure only.** The repository is a fresh copy of
the `django-template` starter: two apps, `core` and `accounts` (login by
email, account page, two-factor authentication). None of the domain apps
(`fiscal`, `banking`, `invoices`, `deadlines`, `dashboard`) exists yet, and
the starter's defaults are untouched: signup is still open
(`DJANGO_ACCOUNT_SIGNUP_OPEN`), which a single-user ledger must close before
it is deployed. GitLab CI (`.gitlab/.gitlab-ci.yml`) runs the checks on merge requests and the
default branch.

Read before building anything:

- `docs/architecture.md` — layout, app boundaries, backing services (Postgres, S3, Supabase rules), conventions
- `docs/worktrees.md` — parallel stacks for worktrees and agents: names, ports, `.env`, mounted source, cleanup
- `docs/domain.md` — what each app must do

`README.md` holds only the three quickstarts (dev, local, selfhost) and the
index of `docs/`: keep it short and put everything else in `docs/`
(`architecture.md`, `domain.md`, `development.md`, `deployment.md`,
`selfhosting.md`, `makefile.md`, `worktrees.md`). Keep the docs in sync with the code and the
`Makefile`.

## Layout

```
django/     Django project (pyproject.toml, package.json, manage.py, apps/, config/)
supabase/   Supabase CLI config + SQL migrations (schemas, buckets only)
docker/     Dockerfile, nginx/, certbot/ (Let's Encrypt sidecar),
            compose.dev.yaml (local Supabase), compose.local.yaml (dev server on
            a hosted project), compose.staging.yaml / compose.prod.yaml (TLS,
            single-purpose server), compose.selfhost.yaml (behind your proxy;
            self-contained, + compose.selfhost.build.yaml to build from a clone)
scripts/    worktree-env.sh: identity, ports and .env of this worktree (`make env`)
tests/      pytest/test-postgres.sh (runner behind `make test`: throwaway Postgres),
            smoke/ (smoke.sh + its compose overlay, behind `make smoke`);
            the unit tests themselves live in django/apps/<app>/tests/
.config/    pre-commit.yaml (git hooks), gitleaks.toml, hadolint.yaml
docs/       architecture, domain (what each app must do), development, deployment,
            selfhosting, makefile (targets by scenario), worktrees
.gitlab/    .gitlab-ci.yml: CI on a Docker-socket runner (tag `local`): MRs and the default
            branch only, every job calls a make target; git hooks run locally only
```

## Commands

Run from the repository root; the Makefile `cd`s into `django/`.

```bash
make setup          # first run: deps, hooks, supabase, env, migrate, superuser, translations, checks
make worktree-up    # THE way to run the app: this worktree's Supabase project, .env, dev server in Docker on its port (8100 in the primary checkout). Detached: returns when the server answers, fails with its log otherwise. Code, templates and CSS are live (mounted); run it again after changing uv.lock or translations
make worktree-logs  # follow the dev server log (mail and confirmation links are printed there)
make worktree-info  # this worktree's instance name, app URL, database port, Supabase API URL
make worktree-list  # every worktree of the repository: branch, URL, dev server / Supabase up or down
make worktree-prune # remove what worktrees deleted without worktree-destroy left behind (lists, then asks)
make worktree-down  # close everything: remove this worktree's dev containers, stop its Supabase project (data kept)
make worktree-destroy # DESTRUCTIVE: its containers, images and Supabase project; before `git worktree remove`
make env            # create / refresh .env: Supabase ports, dev port (never touches other lines)
make env-port       # choose the dev port again (when the preflight says it is taken)
make supabase-list  # every local Supabase project on this machine
make migrate        # Django migrations (+ schema creation + RLS)
make check          # manage.py check + check_services (schema, RLS, bucket)
make lint / format  # ruff + import-linter (app dependency direction) / ruff autofix
make typecheck      # mypy + django-stubs
make hooks-run      # all pre-commit hooks on all files (ruff, mypy, shellcheck, hadolint); not in CI
make secrets        # gitleaks over the whole git history (Docker)
make ci-lint        # validate the GitLab CI file against GitLab (glab ci lint, glab 1.131.0+)
make messages       # extract strings to django/locale; then make compilemessages
make test           # pytest on a throwaway Postgres container (Docker only); ARGS="-k ..."
make test-supabase  # same suite on the local Supabase database
make smoke          # build images, run the real stack, check it from outside (~1 min)
make local-up       # personal use: the UI in Docker on :8003, real data on a hosted project (.env.local)
make staging-up     # nginx (TLS) + gunicorn + certbot, hosted STAGING Supabase (.env.staging)
make prod-up        # same stack, hosted PRODUCTION Supabase (.env.prod); asks to confirm
make selfhost-up    # nginx (plain HTTP) + gunicorn behind the machine's reverse proxy; any Postgres + S3 (.env.selfhost)
make staging-push   # supabase/migrations -> staging project (prod-push for production)
cd django && uv run pytest apps/core/tests/test_rls.py::test_every_django_table_has_rls_enabled
cd django && uv run manage.py makemigrations <label>
cd django && uv add <pkg>      # dependencies — never pip
```

The local Supabase project of the worktree must be running (`make supabase-start`)
for `make env`, `migrate`, `check` and `test-supabase`; `make worktree-up`
starts it.
`make test` and `make smoke` need Docker, not Supabase. `make typecheck` and
`make test` load the settings, so they need a `.env` (`cp .env.example .env`
on a fresh clone, as CI does). `make messages` / `compilemessages` need GNU
gettext. The Supabase CLI must be 2.121.0 or later; glab (`make ci-lint`)
1.131.0 or later.

In a git worktree run `make install worktree-up`: never start the stack of
another worktree, and never assume port 8000 or 54322 — `make worktree-info`
prints the real ones.

## Local environment

- Each worktree has its own stack and its own ports. Never assume the port.
- Run `make worktree-info` to get the app URL, the Supabase URLs and the instance name.
- The stack is already running when you start. If it is not, run `make worktree-up`.
- Run `make worktree-destroy` only when the human expressly asks for it: the
  worktree is usually removed by the human.

## Rules that are easy to break

- **Dependency direction**: `dashboard > deadlines > invoices > fiscal | banking
  > accounts > core`. Import only downwards. `make lint` enforces it
  (import-linter contract in `django/pyproject.toml`, which lists only
  `accounts` and `core` today): add each domain app to the contract when
  creating it.
- **No hard-coded local port or container name**: stacks run in parallel (one
  per worktree, one per project). Names derive from `PROJECT` and the instance
  of the worktree (`WORKTREE_INSTANCE`), ports from `.env` (`DJANGO_DEV_PORT`,
  `DB_PORT`, `S3_ENDPOINT_URL`, written by `make env`) or are picked free at
  run time (tests, smoke). Never write a port in `supabase/config.toml` (stack
  mode assigns them), and never use `docker volume rm`, `docker system prune`
  or `supabase stack stop --all` in a target or a script: they reach beyond
  the current worktree (`worktree-prune` is the one exception: it only
  removes what no existing worktree owns, after asking). A worktree keeps its
  dev port while it exists: never edit `DJANGO_DEV_PORT` by hand, and never
  run `worktree-prune` or another worktree's targets from an agent. See `docs/worktrees.md`.
- **The dev server runs in Docker only** (`make worktree-up`: Django and the
  Tailwind watcher of `docker/compose.dev.yaml`; `make worktree-down` closes
  it). The source folders are mounted read-only and the server listens on
  `127.0.0.1`: do not go back to `docker compose watch`, to `0.0.0.0`, or to
  mounting the whole of `django/` (its `.venv` would hide the image's). No Node.js or `runserver` on
  the host, and no make target for them: the host keeps `uv` for lint, tests
  and `manage.py` commands. Keep the Makefile small: no target that only
  wraps one command of another tool.
- **`django/` is a folder, not a package**: never add `django/__init__.py` — it
  would shadow the Django library when Python runs from the repository root.
- **Imports vs labels**: import as `apps.invoices...`; refer to models by label
  (`"invoices.Fattura"`, `settings.AUTH_USER_MODEL`).
- **Logic placement**: business rules in `services.py` (writes) and
  `selectors.py` (reads), not in admin, templates or `save()`.
- **Generic app, Supabase harness**: code under `django/` must run unchanged
  on a plain Postgres and any S3 store — settings are `DB_*` / `S3_*`, no
  Supabase-specific SQL, tables or URLs outside `supabase/` (the one exception
  is the extra bucket check in `check_services`). selfhost never applies
  `supabase/migrations/`; keep `.env.selfhost.example` free of Supabase.
- **Supabase** (dev, staging, prod): Django connects as the `partitario_app` role, never `postgres`,
  and no password goes into `supabase/migrations/`; tables stay in the
  `partitario` schema with RLS enabled and no policies; never add `partitario` to `[api].schemas`; the `documents` bucket stays
  private and files go through `FileField` / signed URLs only.
- **Migrations**: app tables via Django migrations; `supabase/migrations/` only
  for what Django cannot own. Never edit an applied migration.
- **Money** is `Decimal`, never float.
- **Fiscal years are immutable in effect**: new-year rules never change a past
  year's results.
- **`make prod-*` touches the production Supabase project**, which holds the
  real data: never run those targets without being asked. Try changes on
  staging first (`make staging-*`).
- **Staging mirrors prod**: `docker/compose.staging.yaml` and
  `compose.prod.yaml` must stay identical except for the environment name;
  change both together.
- **Two ways to face the world**: staging / prod terminate TLS themselves
  (nginx + certbot, ports 80/443); `compose.selfhost.yaml` serves plain HTTP on
  a loopback port and leaves TLS to the machine's reverse proxy. The
  application's nginx config lives once, in `default.conf.template`;
  `tls.conf.template` only fronts it. No proxy-specific config in the repo:
  that goes in the gitignored `docker/compose.override.yaml` (selfhost only).
- **Secure by default**: with `DEBUG` off, HTTPS redirect, HSTS and secure
  cookies are on (`config/settings.py`); do not add settings that weaken them
  for the hosted stacks. nginx is the only published container.
- **No admin password in hosted env files**: `ensure_superuser` and
  `DJANGO_SUPERUSER_*` are local-development only; the hosted stacks use
  `make <env>-superuser` (interactive).
- **`local-*` is not a development environment**: it is how one person uses
  the app, with the UI on their machine and their real data on a hosted
  project (`.env.local`). Develop on `make worktree-up`. It runs `runserver`
  with `DEBUG` on, so it must stay bound to `127.0.0.1`; never run
  `local-migrate` or `local-push` without being asked.
- **`django/static/css/.gitkeep` stays tracked** too: it is the mount point
  of the dev stylesheet volume, which Docker would otherwise create as root.
- **`django/static/.gitkeep` stays tracked**: the only other content of
  `static/` is the gitignored `css/app.css`, and without the directory a fresh
  clone fails both `check --deploy` and the Docker build.
- **Fixed container user**: the application image runs as uid/gid `10001`,
  which owns the `media` volume; changing it orphans existing volumes.
- **Hook and linter config lives in `.config/`**, not in the root: every
  invocation names it (`make hooks`, `make hooks-run`, `make secrets`).
- `PartitaIva2026.xlsx` is real financial data: never commit it or copy its
  figures into fixtures or docs.

## Conventions

- Ruff lints and formats (line length 100); run `make format` before finishing.
- Git hooks are the pre-commit framework (`.config/pre-commit.yaml`, next to
  the gitleaks and hadolint settings).
- Tests in `apps/<app>/tests/test_*.py`, against real Postgres; shared fixtures
  in `django/conftest.py`. Before finishing: `make lint typecheck test`;
  `make hooks-run` after touching shell scripts or the Dockerfile (CI does
  not run the hooks); `make smoke` after touching `docker/`, nginx config or settings
  that change HTTP behaviour — and add a smoke check for what you changed.
- After changing `.gitlab/.gitlab-ci.yml`, run `make ci-lint` and fix any error before committing.
- Code is type-annotated: mypy rejects untyped functions outside tests and
  must stay clean (no blanket `# type: ignore`).
- Settings read the environment only through `config/env.py` (`env_str`,
  `env_bool`, `env_int`, `env_list`), never `os.getenv`. Env names are
  prefixed by group: `DJANGO_*`, `DB_*`, `S3_*`, `EMAIL_*`, `TURNSTILE_*`.
- In `apps/core`: plain functions in `schema.py` / `diagnostics.py`, signal
  receivers in `signals.py`, thin management commands. Its only table is the
  maintenance switch (`MaintenanceMode`).
- The cache is shared between workers: a database table by default
  (`django_cache`, created by `migrate`), Valkey/Redis with `DJANGO_CACHE_URL`.
  Never rely on per-process memory for state; do not cache a query in the
  database cache to save a query.
- Error pages (`templates/4xx.html`, `5xx.html`, `errors/base.html`) stay
  self-contained: no `{% static %}`, no context processors, no queries.
- Impersonation (django-hijack): the rule is `apps/accounts/permissions.py`;
  keep it strict and keep the audit log in `apps/accounts/signals.py`.
- Files: always through `FileField` / `default_storage` and `.url`, so both
  storage backends (S3, filesystem) keep working and documents stay private.
- Authentication pages come from django-allauth (`/accounts/`): signup,
  login, address, password, second factor. It is the only login:
  `/admin/login/` redirects to it (`config/urls.py`), never add another way
  in. Staff must have two-factor authentication outside `DEBUG`
  (`apps/accounts/middleware.py`); tests switch it off in `conftest.py`.
  Style the account pages through `templates/allauth/` (layout + elements),
  not page by page.
- A user is an email address with a UUID key: no username, no first or
  last name (`USERNAME_FIELD = "email"`, on `AbstractBaseUser`). Addresses
  are lowercase (manager, `User.clean()`, a database constraint): create
  users with `create_user` or a model form, and lower the address yourself
  in `bulk_create` / `update()`. Never assume the key is an integer (`str(user.pk)` in URLs
  and sessions).
- Nobody logs in before confirming their address
  (`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`); only `create_superuser`
  counts as verified. A user created or edited outside allauth goes through
  `services.sync_email_address`. In tests use the `create_user` fixture of
  `conftest.py`, which confirms the address.
- Signup is open (`DJANGO_ACCOUNT_SIGNUP_OPEN`) behind Cloudflare Turnstile
  (`TURNSTILE_*`, `apps/accounts/turnstile.py`): off in the local stack and
  in tests, Cloudflare's test keys in dev and staging, real keys in prod and
  selfhost — enforced at startup by `apps/accounts/checks.py`, the one place
  that reads `ENV`. Do not weaken it, and keep it failing closed when
  Cloudflare cannot be reached.
- Logins, failures and second-factor changes are logged by
  `apps/accounts/signals.py`: keep the audit log when touching authentication.
- Background work is a Django task (`@task` in `apps/<app>/tasks.py`,
  `.enqueue()` with JSON arguments: ids, not objects). It runs at once under
  `DEBUG` and in tests, in the `worker` container otherwise. Mail is always
  sent the normal way (`send_mail`, `EmailMessage.send()`): the default mailer
  queues it (`apps/core/mail.py`). Never talk to `MAILERS["transport"]`
  from a request.
- The Content Security Policy is enforced (`SECURE_CSP`): a new external
  origin (CDN, embed, analytics) must be added to it, and no page may rely on
  it being report-only.
- UI is the Unfold admin (`unfold.admin.ModelAdmin`, navigation in
  `UNFOLD["SIDEBAR"]`). Prefer Unfold components and its bundled HTMX, Alpine
  and Chart.js before adding a JS dependency; style with Tailwind using the
  `primary-*` / `base-*` palette.
- The account page (`/accounts/`, `apps/accounts/views.py`) is where a login
  lands for whoever is not staff, and where a user deletes their own account
  (password asked again, logged, never for superusers or while
  impersonating). Everything else about an account is an allauth page.
- Without `EMAIL_HOST` mail is printed to the log by
  `apps.core.mail.ConsoleEmailBackend`, not Django's console backend, which
  cuts long links in two.
- `CHANGELOG.md`: one entry per release, newest first (`## [vX.Y.Z] - date`,
  then `### Added` / `Changed` / `Fixed`).
- UI source strings are English, wrapped in `gettext`; the Italian shown by
  default lives in `django/locale/it/LC_MESSAGES/django.po` — after adding a
  string run `make messages`, translate it, `make compilemessages` (`.mo` is
  not committed). Code and comments are English; Italian fiscal terms without
  a clean translation (fattura, scadenza, acconto, saldo, bollo) stay Italian
  in model and field names.
