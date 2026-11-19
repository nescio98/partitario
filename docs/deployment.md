# Staging and production

Two hosted environments, each with its data in **its own hosted Supabase
project**, run the same Docker stack on a single-purpose server facing the
internet. For a machine that already has a reverse proxy, see
[selfhosting.md](selfhosting.md).

```
internet ─▶ nginx :80/:443 ─▶ gunicorn (Django) ─▶ Supabase (Postgres + Storage)
              ▲ certificate
            certbot (Let's Encrypt, HTTP challenge, automatic renewal)
```

| Environment | Env file       | Make targets | Supabase project |
|-------------|----------------|--------------|------------------|
| staging     | `.env.staging` | `staging-*`  | staging          |
| production  | `.env.prod`    | `prod-*`     | production       |

Staging is an exact copy of production: `docker/compose.staging.yaml` and
`docker/compose.prod.yaml` are identical except for the environment name. Use
staging to try migrations and new code before they touch the real data.
`make prod-push`, `make prod-up` and `make prod-superuser` ask for confirmation.

## Preparing a Supabase project

Once per project (shown for staging; replace with `prod`):

1. Create the Supabase project and run `supabase login` once.
2. `make staging-env` and fill in `.env.staging` (gitignored). Every value and
   where to find it is described in `.env.hosted.example`.
3. `make staging-push DRY=1`, then `make staging-push`: creates the
   `partitario_app` role, the `partitario` schema and the private `documents`
   bucket. The target project is `SUPABASE_PROJECT_REF` in the env file, so no
   `supabase link` is needed and two projects cannot be mixed up.
4. Give the role its password, once, in the dashboard SQL editor — the same
   value as `DB_PASSWORD` in the env file:
   `alter role partitario_app with password '<database password>';`
5. Signup: configure the mail server (`EMAIL_*`), or nobody can confirm
   their address — and for production create a Turnstile widget for the host
   name (Cloudflare dashboard → Turnstile; free, the site need not be behind
   Cloudflare) and set `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`: the
   production stack does not start on Cloudflare's test keys, which staging
   uses by default. A site without public signup sets
   `DJANGO_ACCOUNT_SIGNUP_OPEN=False` instead.
6. Harden the project in its dashboard: disable the Data API and Supabase's own user
   signups (neither is used: accounts live in Django), enforce SSL on the database, restrict database network
   access to the server address, and enable backups.

A project used by the [local quickstart](../README.md#local-quickstart) needs
the same steps with the `local-*` targets (`make local-env`,
`make local-push`) and `.env.local`; the Let's Encrypt values of the template
are not used there.

## Preparing the server

Point the DNS of the host name (`DJANGO_ALLOWED_HOSTS`) at the server and open
ports 80 and 443. Docker is the only requirement.

## Deploying

```bash
make staging-up         # build (or pull), migrate, start
make staging-superuser  # first time only: create the admin user (asks for the password);
                        # the first login then asks to set up two-factor authentication
make staging-check      # schema, RLS and bucket round trip on the hosted project
make staging-logs       # follow the logs (gunicorn, task worker, nginx, certbot)
make staging-backup     # pg_dump of the schema into backups/ (gitignored)
make staging-down       # stop (hosted data and certificates are kept)
```

- The containers restart with Docker and apply pending Django migrations on
  every start; run `make <env>-up` again after pulling new code.
- New files in `supabase/migrations/` still need `make <env>-push`.
- To run a published release instead of building from the checkout, set
  `PARTITARIO_IMAGE` and `PARTITARIO_VERSION` in the env file: `up` then
  pulls that exact version, and going back is a matter of changing the number.
- The admin user is created by hand, once per project, so its password never
  sits in an env file or in the container environment.

## A faster cache (optional)

The cache is a table in the database by default. To use the bundled Valkey
instead, set `COMPOSE_PROFILES=cache` and
`DJANGO_CACHE_URL=redis://cache:6379/0` in the env file and run `up` again
([architecture.md](architecture.md#cache)).

## Maintenance mode

Switch it with the "Maintenance mode" entry of the admin, or from the server
(shown for staging):

```bash
docker compose --env-file .env.staging -f docker/compose.staging.yaml \
    exec web python manage.py maintenance_mode on    # or: off
```

Visitors get a maintenance page with HTTP 503; staff and the admin site keep
working. Details in
[architecture.md](architecture.md#maintenance-mode).

## TLS

HTTPS is enforced. nginx starts with a self-signed placeholder certificate;
the `certbot` container then obtains the real one for every name in
`DJANGO_ALLOWED_HOSTS`, nginx picks it up within 30 seconds, and renewals are
automatic. While trying the setup, set `LETSENCRYPT_STAGING=true` to stay
clear of Let's Encrypt rate limits.

## What is hardened

- **nginx** (`docker/nginx/`): TLS 1.2/1.3 only, HTTP → HTTPS redirect,
  unknown host names dropped, forwarded headers rewritten, login and signup POSTs rate
  limited (`/admin/login/`, `/accounts/login/`, `/accounts/signup/`), hashed static files cached
  for a year, runs unprivileged.
- **Django** (with `DEBUG` off): HTTPS redirect, HSTS, `__Host-` secure
  cookies, 8-hour sessions, Argon2 password hashes, an enforced Content Security Policy,
  logs on stdout. One login page for everybody (the admin redirects to it),
  with a lockout after 5 failed attempts per address, mandatory two-factor
  authentication for staff and an audit log of logins. Signup needs a
  confirmed email address and sits behind Cloudflare Turnstile: production
  does not start on its test keys (see
  [architecture](architecture.md#authentication)). `DJANGO_SECURE_HSTS_SECONDS` starts at one hour: raise it to
  one year once HTTPS works.
- **Containers**: read-only filesystem, no capabilities, no privilege
  escalation, memory and process limits, rotated logs, healthchecks (the
  application is healthy only while its database answers). The application
  runs as the fixed uid/gid `10001`.
- **Database**: Django connects as `partitario_app`, which owns only the
  `partitario` schema; the connection is encrypted (`DB_SSLMODE=require`).
