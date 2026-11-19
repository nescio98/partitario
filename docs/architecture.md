# Architecture

## Stack

| Layer      | Choice                                                                    |
|------------|---------------------------------------------------------------------------|
| Language   | Python 3.13, managed with [uv](https://docs.astral.sh/uv/)                |
| Framework  | Django 6.1                                                                |
| Admin / UI | [django-unfold](https://unfoldadmin.com/) 0.110.1                         |
| Frontend   | Tailwind CSS 4 (CLI), plus the HTMX, Alpine.js and Chart.js Unfold ships  |
| Auth       | Django auth + [django-allauth](https://docs.allauth.org/) (email login, signup with a verified address, Turnstile) |
| Database   | PostgreSQL, dedicated `partitario` schema and role, RLS everywhere       |
| Files      | Private: an S3-compatible bucket (signed URLs) or a local volume (login-protected) |
| Backing    | Supabase (Postgres + Storage) for dev, staging and production; bundled or any Postgres / S3 when self-hosting |
| Tasks      | Django's tasks framework, queued in the database ([django-tasks-db](https://pypi.org/project/django-tasks-db/)) and run by a `worker` container; mail goes through it |
| Hosting    | Docker: nginx → gunicorn, plus the task worker; staging / production (TLS) and self-hosting; images for amd64 and arm64 |
| I18n       | English source strings, Italian by default (`django/locale/it`)           |
| Quality    | Ruff, mypy + django-stubs (typed code enforced), import-linter, pytest, end-to-end smoke test; pre-commit hooks (gitleaks, shellcheck, hadolint, actionlint) |

## Repository layout

```
/                 orchestration only: Makefile, .env(.example), README, .claude/
├── django/       the Django project — self-contained Python project (+ Tailwind, run in Docker)
├── supabase/     Supabase CLI project: config.toml and SQL migrations
├── docker/       Dockerfile (+ its .dockerignore), compose files, nginx/, certbot/
├── tests/        pytest/test-postgres.sh behind `make test`, smoke/ behind `make smoke`
├── scripts/      worktree-env.sh: the identity, ports and .env of this worktree
├── .config/      git hooks and linter settings: pre-commit, gitleaks, hadolint
├── .github/      CI: quality gates, smoke test, images and release on a v* tag
└── docs/         this folder
```

`django/` owns `pyproject.toml`, `uv.lock`, `package.json` and `manage.py`, and is
the Docker build context: the image never sees anything outside it. Run tools
through the root `Makefile`, or `cd django` first.

`django/` is a plain folder, not a Python package: never add an `__init__.py`
to it, or it would shadow the real `django` library for anything run from the
repository root.

```
django/
├── config/       settings, env.py (typed environment access), urls, wsgi
├── apps/         every Django app, imported as `apps.<name>`
├── templates/    project-level templates (Unfold overrides, layouts)
├── static/       project static files; `css/app.css` is generated and gitignored,
│                 `.gitkeep` keeps the folder in a fresh clone (the build needs it)
├── locale/       translations of the English source strings (it)
├── gunicorn.conf.py  workers, threads, timeouts of the hosted stacks
├── tailwind/     Tailwind entry point -> static/css/app.css (generated)
└── conftest.py   fixtures shared by all apps
```

## Apps and dependency direction

| App         | Owns                                                                  |
|-------------|-----------------------------------------------------------------------|
| `core`      | Infrastructure: schema, RLS and the cache table, health endpoints, private media, service checks, maintenance mode (its one model) |
| `accounts`  | Custom `User` (email address instead of a username, UUID key), signup behind Turnstile, the account page, mandatory two-factor authentication for staff, impersonation rule, audit log of logins |

Those two exist. The domain apps are planned, not created yet; what each must
do is in [domain.md](domain.md):

| App         | Will own                                                              |
|-------------|-----------------------------------------------------------------------|
| `fiscal`    | Tax configuration per fiscal year (parameters only)                   |
| `banking`   | Banks/brokers, conto corrente, conto titoli, derived estratto conto   |
| `invoices`  | Fatture and their uploaded documents                                  |
| `deadlines` | Scadenze: generation per year, reconciliation against bank movements  |
| `dashboard` | Read-only overview; owns no models                                    |

An app may import only from apps **below** it:

```
dashboard
deadlines
invoices
fiscal | banking      (independent of each other)
accounts
core
```

`deadlines` is separate from `fiscal` on purpose: scadenze need invoices (bollo
per quarter) and bank movements (paid or not), while invoices need the fiscal
parameters. Keeping scadenze out of `fiscal` avoids a cycle.

The rule is enforced: `make lint` runs import-linter (`lint-imports`) with a
layers contract declared in `django/pyproject.toml`, so an upward import fails
the hook and CI. The contract lists `accounts` and `core` today: add each
domain app to it when creating it, in the order above; two apps that must stay
independent of each other go on the same line (`"fiscal | banking"`).

App labels are the short names (`accounts`, `core`): use them in
`AUTH_USER_MODEL`, foreign-key strings and admin URL names. Python imports use
the full path (`apps.accounts.models`).

## Inside an app

```
<app>/
├── models.py       data model
├── services.py     write side: business operations, plain functions
├── selectors.py    read side: queries and aggregations, no side effects
├── admin.py        Unfold registrations, presentation only
├── migrations/
└── tests/          test_*.py
```

Business rules live in `services.py` / `selectors.py`, never in admin
classes, templates or `Model.save()`. That keeps them testable without the UI.

## Backing services

The application depends on two services only, both through standard
protocols: a **PostgreSQL** database (`DB_*` settings) and a store for
uploaded documents, chosen by `DJANGO_STORAGE_BACKEND`: an **S3-compatible**
bucket (`s3`, the default; `S3_*` settings, django-storages) or a **local
directory** (`filesystem`, `DJANGO_MEDIA_ROOT`). Nothing in
`django/` imports or calls anything Supabase-specific; the one exception is an
extra check in `check_services` (`apps/core/diagnostics.py`) that only runs when the S3 endpoint is a
Supabase one.

| Environment            | Postgres and S3 come from          | Provisioned by                         |
|------------------------|------------------------------------|----------------------------------------|
| dev, tests             | local Supabase CLI project of the worktree | `supabase start` (migration + seed) |
| staging, prod, local   | a hosted Supabase project each     | `make <env>-push`                      |
| selfhost               | bundled Postgres + a volume by default; or any Postgres 14+ / S3 store | the stack itself; Django creates the schema |

Keep it that way: code under `django/` must run unchanged on a plain Postgres
and a generic S3 store. Supabase-only objects (API roles, `storage.buckets`)
belong in `supabase/migrations/`, which selfhost never applies.

### Documents are private on both backends

- `s3`: the bucket is private and `FileField.url` is a signed URL valid for
  5 minutes.
- `filesystem`: there is no public media location. `FileField.url` points at
  `/media/<path>`, answered by `apps/core/views.py::protected_media`, which
  requires a login, resolves the path through the storage (nothing outside
  `MEDIA_ROOT`) and then hands the transfer to nginx through
  `X-Accel-Redirect` to an `internal` location (Django streams the file
  itself under `runserver`). Uploads are untrusted: they are served with
  `nosniff` and a sandboxing CSP.

Code that stores files must go through `FileField` / `default_storage` and
use `.url`, never build paths or URLs by hand: that is what keeps both
backends working.

### On Supabase

Supabase is used as plain Postgres plus an S3-compatible file store. The
Data API and Supabase Auth are not used.

- **Role**: Django connects as `partitario_app`, created by the Supabase
  migration, never as `postgres`. The role owns the `partitario` schema and has
  no other privilege. Its password is not in the repository: `supabase/seed.sql`
  sets a public development one locally (and `CREATEDB` for the pytest
  database); on a hosted project it is set once in the SQL editor.
- **Schema**: all Django tables live in `partitario` (via `search_path`, set both
  on the role and on the connection), never in `public`, and `partitario` is
  not listed in `[api].schemas`, so the REST/GraphQL API cannot reach them.
- **RLS**: `apps/core/schema.py` enables Row Level Security on every table
  after each `migrate` (`apps/core/signals.py`, `post_migrate`, connected for
  the core app only so it runs once). No policies: the owner role bypasses RLS,
  every other role is denied. `apps/core/tests/test_rls.py` enforces this.
  `pre_migrate` creates the schema only where it is missing (the pytest
  database, and a self-hosted database on first start). Off Supabase RLS
  protects against nothing in particular and costs nothing: it stays on
  everywhere so there is one behaviour to test.
- **Storage**: the `documents` bucket is private with no storage policies.
  `STORAGES["default"]` is django-storages S3, so a `FileField` uploads
  there and `.url` is a signed URL valid for 5 minutes. `check_services`
  verifies from the outside that the bucket refuses unsigned requests: the
  object URL without its signature on any store, plus Supabase's public
  object URL when the endpoint is Supabase.
- **Connection**: direct or session-mode pooler only (the `search_path`
  startup option is ignored by the transaction-mode pooler, port 6543).
  `DB_SSLMODE=require` on hosted projects.

Two kinds of migration:

| What                                      | Where                         | Applied by                      |
|-------------------------------------------|-------------------------------|---------------------------------|
| Application tables                        | `django/apps/<app>/migrations/`  | `make migrate`                  |
| Supabase-level objects (role, schema, bucket) | `supabase/migrations/`    | `supabase start` / `make <env>-push` |
| Local-only setup (dev password)           | `supabase/seed.sql`           | `supabase start` / `make db-reset` |

Tables created outside Django migrations must enable RLS themselves.

Locally the CLI runs in **stack mode** (`stack = true` in
`supabase/config.toml`, Supabase CLI 2.121.0 or later): every worktree and
every branch is its own local project, with its own database and storage, on
ports the CLI chooses and keeps. `config.toml` therefore sets no port, and
nothing else may hard-code one: `make env` reads them from
`supabase status` into `.env` (`DB_PORT`, `S3_ENDPOINT_URL`). See
[worktrees.md](worktrees.md).

## Cache

One cache shared by every gunicorn worker and container. Django's default, a
private memory cache per process, makes anything counted in it or invalidated
through it unreliable: allauth's rate limits would be counted per worker and
reset whenever a worker is recycled.

| | Default: database | Opt-in: Valkey / Redis |
|---|---|---|
| Setting | none | `DJANGO_CACHE_URL=redis://cache:6379/0` |
| Service | none: the `django_cache` table, created by `migrate` | compose profile `cache` (bundled Valkey), or any Redis |
| Good for | correctness: shared counters, invalidation | speed: caching expensive queries or fragments |

The database cache does not make anything faster — do not cache a query in it
to save a query. That is why the maintenance-mode lookup stays a direct query.
`check_services` round-trips a value through whichever cache is configured.

allauth counts its limits per client address. Behind nginx the connection
always comes from nginx, which overwrites `X-Forwarded-For` with the one
address it trusts, so `ALLAUTH_TRUSTED_PROXY_COUNT` is 1 with `DEBUG` off and
0 under `runserver`.

## Authentication

Django auth with the custom `accounts.User`. django-allauth provides the
account pages under `/accounts/`: signup, login, logout, email address,
password change and reset, two-factor authentication, sessions. Until a mail
server is configured the mails (confirmation and reset links included) are
printed to the log, readable as sent (`MAILERS` in settings).

**The user is an email address.** `accounts.User` is built on Django's bare
`AbstractBaseUser`: no username and no first or last name
(`USERNAME_FIELD = "email"`, `ACCOUNT_LOGIN_METHODS = {"email"}`). A project
that needs a name adds its own field. Its
primary key is a random UUID, so it can appear in a URL or a log without
revealing how many users there are. Addresses are lowercase, hence unique
whatever their casing: the manager (`create_user`, `createsuperuser`) and
`User.clean()` (every model form) lower them, a check constraint in the
database refuses anything else, and login lowers what was typed. A user
created with `bulk_create` or a raw `update()` skips the normalization and
meets the constraint: lower the address yourself.

**Signup** is open (`DJANGO_ACCOUNT_SIGNUP_OPEN=False` closes it in
`apps/accounts/adapter.py`: users are then only created in the admin). The
form is allauth's with a Turnstile field (`apps/accounts/forms.py`), and
nginx limits its POSTs like those of the login. Signing up with an address
that is already registered answers like any other signup; only the owner of
the address is told, by mail.

**Verified addresses.** `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`: nobody
logs in before following the link mailed to their address — after signing
up, or at the first login for a user created in the admin
(`services.sync_email_address` keeps allauth's record in step with what the
admin saves, so an address replaced there stops working). The exception is
`create_superuser` (`createsuperuser`, `ensure_superuser`): whoever runs it
has a shell on the server, and the first administrator must get in before
any mail works, so that address counts as verified. A user changes their own
address under `/accounts/email/`: the new one replaces the old once
confirmed.

**Bot protection.** Cloudflare Turnstile on the signup form only: its script
decides whether a person is there, usually without asking anything, and adds
a token to the form, which the server has Cloudflare confirm before creating
anybody (`apps/accounts/turnstile.py`: a widget, a field and one POST, no
package). If Cloudflare cannot be reached the signup is refused, not waved
through. The Content Security Policy allows `challenges.cloudflare.com` as a
script and frame source while it is on.

| Environment      | Turnstile                                                         |
|------------------|-------------------------------------------------------------------|
| local            | off: `compose.local.yaml` sets `TURNSTILE_ENABLED=False`           |
| dev, staging     | Cloudflare's public test keys (the default): the widget shows, everybody passes |
| prod, selfhost   | the site's own `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`       |
| tests            | off (`conftest.py`); the tests of the field replace Cloudflare's answer |

Production cannot run on the test keys by mistake: the system check
`accounts.E001` (`apps/accounts/checks.py`) fails every management command,
`migrate` included, so the `web` container does not start. It is the one
place that looks at `ENV`, because staging and production are otherwise the
same configuration.

**The account page** (`/accounts/`, `apps/accounts/views.py`) is where a
login lands for anybody who is not staff (`home` sends staff to the admin):
the address, whether it is verified, and the way to allauth's pages for the
address, the password, the second factor and the sessions. It is also where a user deletes their own
account (`/accounts/delete/`): the password is asked again, it is logged, and
it is refused to superusers (another one removes them in the admin) and
while impersonating.

**One login.** The admin has no login form of its own: `/admin/login/`
redirects to `/accounts/login/` (`secure_admin_login` in `config/urls.py`), so
nothing gets in around allauth's rate limits and second factor. Those limits
are allauth's defaults: 5 failed attempts per address every 5 minutes, 10 per
minute per client, on top of nginx's limit on the login URLs.

**Two-factor authentication** (`allauth.mfa`): authenticator app, security
keys, recovery codes, managed by each user under `/accounts/2fa/` (linked
from the account page, itself in the user menu of the admin). It is mandatory for staff when
`STAFF_MFA_REQUIRED` is on — the default with `DEBUG` off, switched by
`DJANGO_STAFF_MFA_REQUIRED`: `apps/accounts/middleware.py` sends a staff
user without a second factor to its setup, whatever page they ask for. The
user list of the admin shows who has one. A user who lost the second factor
and the recovery codes is let back in by a superuser: select them in the user
list and run "Reset two-factor authentication"
(`apps/accounts/services.py::reset_two_factor`, logged with who did it). They
set it up again at the next login. When the only superuser is the one locked
out, the same from the server:

```bash
manage.py shell -c "from allauth.mfa.models import Authenticator; \
    Authenticator.objects.filter(user__email='<address>').delete()"
```

**Password reset** goes by mail. An address nobody registered gets no mail
at all (`ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS`). Changing the address, the password
or the second factor asks for the password again and is notified to the user
by mail.

**Sessions** (`allauth.usersessions`): under `/accounts/sessions/` each user
sees where they are logged in (since when, address, browser) and can end
every other session. "Last seen" is not tracked: it would cost a write on
every request.

**Pages.** The account pages, allauth's and ours, use Unfold's login layout:
`templates/allauth/layouts/base.html` extends it, with the admin context
supplied by `apps.accounts.context_processors.account_pages`, and
`templates/allauth/elements/` gives buttons, fields and panels the admin's
classes. A page allauth adds later is styled without touching it.

**Audit log.** `apps/accounts/signals.py` logs every login (with the client
address), logout, failed login, rejected two-factor code, added or removed
authenticator, and impersonation.

### Impersonation

django-hijack, with Unfold's integration: the user list of the admin has an
"impersonate" button that logs the superuser in as that user, and a banner on
every page to go back. Who may do it is one function,
`apps/accounts/permissions.py::can_hijack` (`HIJACK_PERMISSION_CHECK`): a
superuser may act as any active user except another superuser. Every start
and end is logged at WARNING level by `apps/accounts/signals.py`. The library
has no Italian catalogue, so its few strings are declared in
`apps/accounts/third_party_messages.py` and translated in ours.

## Content Security Policy

Enforced on every response (`SECURE_CSP` in `config/settings.py`): scripts,
styles, fonts and images come from this site only, nothing may be embedded
or frame it, forms post only here. Unfold's Alpine.js needs `'unsafe-inline'`
and `'unsafe-eval'`, so the policy does not stop an injected inline script:
what it stops is anything loaded from another origin. One origin is added
automatically, for images and media: the document bucket's, when documents are
on S3, so a signed URL can be shown inline.

A project that loads something from elsewhere (a CDN, an embedded map, an
analytics script) adds that origin to the policy. To find out what a new page
needs, `DJANGO_CSP_REPORT_ONLY=True` reports violations in the browser
console without blocking them; do not leave it on in production.

## Background tasks and mail

Django's tasks framework (`django.tasks`, `settings.TASKS`). A task is a
function decorated with `@task` in `apps/<app>/tasks.py`, started with
`.enqueue(...)`; arguments and results are JSON, so pass ids, not objects.

| | `DEBUG` (dev, local) and tests | Hosted stacks |
|---|---|---|
| Backend | immediate: the task runs inside the call that enqueues it | database (django-tasks-db): a row in a table |
| Who runs it | nobody to start | the `worker` container, `manage.py db_worker` |
| Switch | `DJANGO_TASKS_IMMEDIATE` (default: `DEBUG`) | |

No broker: the queue is the database, like the cache. The worker runs the
same image as `web`, starts after the migrations, and prunes finished tasks
once a day (successful ones after a day, failed ones after two weeks).
Superusers see what ran and what failed, with the error, under "Background
tasks" in the admin. A task that raises is marked failed and is not retried:
retry inside the task when it makes sense, as `deliver_mail` does.

**Mail never leaves from a request.** `MAILERS["default"]` is
`apps.core.mail.QueuedEmailBackend`: `send_mail()`, `EmailMessage.send()` and
allauth only queue the message, and `apps.core.tasks.deliver_mail` sends it
through `MAILERS["transport"]` (SMTP with `EMAIL_HOST`, otherwise
`apps.core.mail.ConsoleEmailBackend`, which prints the mail to the log as
its reader would see it: Django's own console backend prints it as it
travels, with long lines cut in two, so a copied link does not work). A mail server that is down neither slows a page nor loses the
message: delivery is tried again after one and ten minutes, then logged as
failed. Until it is pruned, a queued mail sits in the task table with its
text, which is why that list is for superusers. Attachments travel as
`(filename, content, mimetype)`.

## Maintenance mode

django-maintenance-mode. While on, every visitor gets `templates/503.html`
with HTTP 503 and a `Retry-After` header; staff, superusers and the whole
admin site keep working, and so do the health checks (answered before any
other middleware). Switch it in the admin ("Maintenance mode") or with
`manage.py maintenance_mode on|off`.

The state is one row of `core.MaintenanceMode`, read on every request by
`apps/core/maintenance.py` (one primary-key lookup). It is in the database
because the library's default, a file, cannot be written on the read-only
container filesystem and would not be shared between workers. If the lookup
fails, maintenance counts as off.

## Error pages

`templates/400.html`, `403.html`, `404.html`, `500.html` and `503.html` extend
`templates/errors/base.html`, which is self-contained: inline styles, no
static files, no context processors, no database. A page shown when something
is broken must not depend on what may be broken. They are translated like any
other template. (Errors raised by nginx itself, such as a 502 while the
application restarts, still use nginx's own pages.)

## Configuration

A single `.env` at the repository root, read by Django (`python-dotenv`) and by
`docker/compose.dev.yaml`. The hosted stacks read `.env.staging` and
`.env.prod`, and `compose.local.yaml` reads `.env.local` (one template for
all three: `.env.hosted.example`); the self-hosted stack reads
`.env.selfhost` (template: `.env.selfhost.example`, no Supabase in it).
Settings read the environment only through `django/config/env.py`
(`env_str`, `env_bool`, `env_int`, `env_list`): a missing required variable or
a malformed one — `ture` for a boolean, text for a number — fails startup
naming the variable, instead of silently becoming a default. A new setting
needs an entry in the env templates.

Variable names carry the prefix of their group: `DJANGO_*` (framework and
application, e.g. `DJANGO_SECURE_HSTS_SECONDS`, `DJANGO_STORAGE_BACKEND`),
`DB_*`, `S3_*`, `EMAIL_*`, `TURNSTILE_*`. Variables read by compose or the Makefile rather
than by Django keep their own names (`ENV`, `COMPOSE_PROFILES`, `HTTP_PORT`,
`PARTITARIO_*`, `LETSENCRYPT_*`, `LOCAL_PORT`, `WORKTREE_INSTANCE`).

In development `.env` belongs to the worktree: `make env`
(`scripts/worktree-env.sh`) creates it and keeps a few keys current — the
instance name, the port of the dev server (`DJANGO_DEV_PORT`) and the ports
of the worktree's local Supabase project. `DJANGO_DEV_PORT` is the one of
these Django reads: under `DEBUG` it suffixes the session, CSRF and language
cookie names (`sessionid_8008`), because browsers do not separate the cookies
of `localhost:8008` and `localhost:8009`. Unset, as in every hosted env file,
it changes nothing.

`ENV` (`dev`, `local`, `staging`, `prod`, `selfhost`) names the environment
and is available as `settings.ENV`. No setting branches on it, and security
never will: everything is derived from `DEBUG`. (One system check reads it, to
refuse Turnstile's test keys in production: see [Authentication](#authentication).) With `DEBUG` off the HTTPS redirect, HSTS, secure
`__Host-` cookies and the proxy header are on by default; each can be
overridden from the environment (`DJANGO_<setting name>`).

## Running modes

| Mode               | Django                            | Postgres + S3            | URL                       |
|--------------------|-----------------------------------|--------------------------|---------------------------|
| `make worktree-up` | runserver in Docker (detached, source mounted, loopback only), plus a Tailwind watcher: the only dev server | local Supabase project of the worktree | `localhost:<port of the worktree>` |
| `make local-up`    | runserver in Docker, loopback only (personal use on real data) | Supabase (`.env.local`) | `localhost:8003` (`LOCAL_PORT`) |
| `make staging-up`  | nginx (TLS) + gunicorn in Docker  | Supabase staging project | `https://<staging host>`  |
| `make prod-up`     | nginx (TLS) + gunicorn in Docker  | Supabase production      | `https://<host>`          |
| `make selfhost-up` | nginx + gunicorn in Docker        | any (`.env.selfhost`)    | behind your reverse proxy |

The port of the worktree is `DJANGO_DEV_PORT` in `.env`: 8100 in the primary
checkout, another one of the project's block of 100 in every other worktree
(`make worktree-info`).

### Hosted stack

Three standalone compose files, each run by the Makefile with its env file
(`.env.<env>`), which gives the host name and the ports:

- `compose.staging.yaml` / `compose.prod.yaml`: a single-purpose server
  facing the internet. nginx terminates TLS on 80/443 and a certbot sidecar
  keeps the Let's Encrypt certificate. The two files are identical except for
  the environment name and run the same image tag: change both together.
- All three run a `worker` container next to `web`: same image, the task
  worker instead of gunicorn (see [Background tasks](#background-tasks-and-mail)).
- `compose.selfhost.yaml`: a machine that already has a reverse proxy. nginx
  speaks plain HTTP on `127.0.0.1:<HTTP_PORT>` and the proxy terminates TLS
  and routes host names, so several apps can share the machine. No certbot.
  The file is self-contained — published images, `env_file` next to it — so
  it also runs without the repository; `compose.selfhost.build.yaml` adds the
  build instructions when working from a clone. It carries an optional
  bundled PostgreSQL (profile `db`) and the `media` volume.
  A gitignored `docker/compose.override.yaml` is merged when present, for what
  is specific to that machine (the proxy's Docker network, labels).

The services:

- **nginx** (`docker/nginx/default.conf.template`, rendered with the host
  names of `DJANGO_ALLOWED_HOSTS`): the application server, plain HTTP on
  8080. Drops requests for unknown hosts, takes the client address and the
  scheme from the `X-Forwarded-For` / `X-Forwarded-Proto` of the proxy in
  front (believed from loopback and private addresses only), redirects
  anything that did not arrive over HTTPS, rewrites the forwarded headers for
  Django, rate-limits login POSTs, serves `/static/` (the output of
  `collectstatic`, baked into its image with hashed names) and proxies the
  rest to gunicorn. Runs as an unprivileged user.
  In staging / production the same nginx also loads `tls.conf.template`,
  which listens on 80/443, terminates TLS and hands every request to the
  server above, exactly as an external proxy would, so the application config
  exists once. There only 80/443 are published; in the self-hosted stack only
  8080 is.
- **web**: gunicorn (`django/gunicorn.conf.py`, WSGI), not published. Runs
  `migrate` on start. The admin user is created once with
  `make <env>-superuser` (interactive `createsuperuser`); `ensure_superuser`
  and the `DJANGO_SUPERUSER_*` variables are for local development only.
- **certbot** (staging / production): Let's Encrypt sidecar. Obtains and
  renews the certificate through the HTTP challenge and publishes a copy to a
  volume nginx reads; `docker/nginx/40-tls-certificates.sh` installs a
  self-signed placeholder until then and reloads nginx when the certificate
  changes.

All of them run with a read-only filesystem, dropped capabilities,
`no-new-privileges`, memory/pid limits and rotated logs. The application
runs as the fixed uid/gid `10001` (the owner of the `media` volume), nginx as
`101`. `apps/core/middleware.py` answers two probes before host validation:
`/healthz` (the process is up) and `/readyz` (the database answers too). The
`web` healthcheck uses `/readyz`, so the container is healthy only while it
can actually serve, and nginx starts after that; nginx does not expose either
probe.

In development `runserver` serves static files itself.

## Static files

With `DEBUG` off the file names carry a content hash, so nginx can cache them
for a year. The storage is `config/storage.py`, Django's
`ManifestStaticFilesStorage` made lenient in one place: `{% static %}` for a
file missing from the manifest serves the unhashed name and logs a warning,
instead of raising and turning the whole page into a 500 — a mistake that
would otherwise show only in production, since `DEBUG` uses the plain
storage. `collectstatic` itself stays strict about broken `url(...)`
references inside stylesheets.

## Frontend

The UI is the Unfold admin. Custom pages use Unfold components and the HTMX,
Alpine.js and Chart.js it already ships. Extra styling is Tailwind 4 utilities,
compiled from `django/tailwind/app.css` (kept outside `static/` so the source
is never collected or published); that file maps `primary-*` and `base-*`
onto Unfold's runtime palette so custom pages follow the theme and dark mode.

## Translations

Source strings are English and wrapped in `gettext`; Italian fiscal terms
without a clean translation (fattura, scadenza, acconto, saldo, bollo) stay
Italian, in model and field names too. The default language is Italian
(`LANGUAGE_CODE = "it"`), served from `django/locale/it/LC_MESSAGES/django.po`
(`LOCALE_PATHS`). `make messages` extracts the strings, `make compilemessages`
compiles them. `.mo` files are gitignored: the image compiles them in its
builder stage, and the smoke test checks an Italian string on the admin index.

## Testing

Five layers, each a make target, all run by CI
(`.github/workflows/ci.yml`; ruff and mypy run there as hooks, inside
`make hooks-run`):

- **`make test`** — pytest + pytest-django against a real PostgreSQL, no
  database mocks. The tests live in `django/apps/<app>/tests/`;
  `tests/pytest/test-postgres.sh` only runs them: it starts a throwaway
  `postgres` container (data in memory, random port) and overrides `DB_*`, so
  the suite needs Docker only; `make test-supabase` runs it on the local Supabase stack
  instead. `django/conftest.py` swaps file storage for in-memory storage so
  tests never touch a bucket, removes the Turnstile field from signup so they
  never ask Cloudflare, and offers `create_user`, a user whose address is
  already confirmed. Settings are evaluated at import, so the
  security defaults are tested in a subprocess
  (`core/tests/test_settings_security.py`), including a clean
  `check --deploy`.
- **`make typecheck`** — mypy with the django-stubs plugin, which loads the
  real settings (so it needs `.env`). Application code must be fully
  annotated (`disallow_untyped_defs`); tests are checked but exempt.
- **`make lint`** — ruff (lint and format) and import-linter, which enforces
  the dependency direction between the apps.
- **`make hooks-run`** — every hook of `.config/pre-commit.yaml` on every
  file: ruff and mypy (through the make targets above), shellcheck on the
  scripts, hadolint on the Dockerfile, actionlint on the workflow, plus the
  guard against data and `.env` files. The gitleaks hook scans what is being
  committed; `make secrets` scans the whole history, and CI runs that one.
  The settings of the hooks, gitleaks and hadolint are in `.config/`, so they
  are always run through the make targets.
- **`make smoke`** — `tests/smoke/smoke.sh` builds the images and starts the
  self-hosted stack (bundled database, documents on disk) with the TLS front
  switched on (`tests/smoke/compose.yaml`), then checks it with curl:
  redirects, unknown hosts, TLS versions, headers, static caching, signup and
  its Turnstile widget, login, the rate
  limit, private documents, the readiness healthcheck, the fixed uid, the
  compiled translations, and that the runtime image holds no tests or
  build sources. Add a check there whenever nginx or the Dockerfile changes.

### Images and releases

The Dockerfile builds two images: the application (`production` target) and
nginx (`nginx` target), which carries the collected static files and its own
configuration (`docker/nginx/`, through the `docker` build context;
`NGINX_TLS=on` selects the TLS front). The builder stage copies an explicit
list of paths and `Dockerfile.dockerignore` keeps host output (bytecode,
`.mo`, uploaded `media/`) out of the context, so tests, Tailwind sources,
lock files and anything built on the host never reach the runtime image, and
compiles the translations (gettext stays in that stage).
The application image runs as the fixed uid/gid `10001`.

Compose files name the images `${PARTITARIO_IMAGE}:${PARTITARIO_VERSION}`. With
no version in the env file `make <env>-up` builds from the checkout; with one
it pulls that release. A `v*` tag makes CI push both images to ghcr.io, for
`linux/amd64` and `linux/arm64` (buildx; arm64 under QEMU, with the CSS stage
built natively), and create a release with `compose.selfhost.yaml` and its
env template.
