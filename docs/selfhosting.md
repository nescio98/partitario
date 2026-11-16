# Self-hosting

`docker/compose.selfhost.yaml` runs the application on a machine that already
has a reverse proxy, such as a homelab VM serving `partitario.home.arpa` next
to other sites. It needs neither Supabase nor, once images are published, the
repository.

```
browser ─▶ your reverse proxy (TLS) ─▶ nginx 127.0.0.1:8080 ─▶ gunicorn ─┬▶ PostgreSQL
                                                                         └▶ documents
```

## Install

**From a clone** — the images are built locally and the secrets generated:

```bash
make selfhost-env        # create .env.selfhost; set DJANGO_ALLOWED_HOSTS and the Turnstile keys in it
make selfhost-up         # build, create the schema and tables, start
make selfhost-superuser  # first time only: create the admin user (then set up two-factor authentication at the first login)
make selfhost-check      # database, RLS, document storage round trip
make selfhost-logs
make selfhost-down       # stop; the database and documents volumes are kept
```

**Standalone** — two files, once the images are in a registry:
`docker/compose.selfhost.yaml` and `.env.selfhost.example`, saved as `.env` in
the same folder. Set `PARTITARIO_IMAGE` / `PARTITARIO_VERSION`, the host
name, the Turnstile keys, and generate the two secrets (the file says how), then:

```bash
docker compose -f compose.selfhost.yaml up -d
docker compose -f compose.selfhost.yaml run --rm web python manage.py createsuperuser
```

Signup is open and sits behind Cloudflare Turnstile: the stack does not start
until `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` hold the keys of a widget
created for the host name (Cloudflare dashboard → Turnstile; free, and the
site need not be behind Cloudflare). The server checks each signup with
`challenges.cloudflare.com`, so it needs outbound HTTPS. Alternatively
`TURNSTILE_ENABLED=False` leaves the form unprotected, and
`DJANGO_ACCOUNT_SIGNUP_OPEN=False` closes signup so that users are only
created in the admin. People who sign up confirm their address by mail, so
configure `EMAIL_*` too.

The images build for `linux/amd64` and `linux/arm64`; publishing them is
described in [development.md](development.md#continuous-integration-and-releases).

## Reverse proxy

nginx in the stack speaks plain HTTP on one port and serves the static files;
TLS and host names belong to your proxy. It must serve the site over HTTPS,
pass the original `Host` header and set `X-Forwarded-For` and
`X-Forwarded-Proto`. Caddy and Traefik do so by default.

```
# Caddy
partitario.home.arpa {
    tls internal        # private name: Caddy's own CA. Omit for a public name.
    reverse_proxy 127.0.0.1:8080
}
```

```nginx
# nginx
server {
    listen 443 ssl;
    server_name partitario.home.arpa;
    # ssl_certificate ...; ssl_certificate_key ...;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

A proxy that runs in a container (Traefik, Nginx Proxy Manager) cannot reach
`127.0.0.1` of the host. Put the stack on its Docker network instead, in
`docker/compose.override.yaml` — gitignored, merged by the `selfhost-*`
targets when it exists — and point the proxy at
`http://partitario-selfhost-nginx-1:8080`:

```yaml
services:
  nginx:
    networks: [default, proxy]
    # labels: ...   # e.g. Traefik routers
networks:
  proxy:
    external: true   # the existing network of your proxy
```

A request that did not reach the proxy over HTTPS is redirected to HTTPS.
nginx believes the forwarded headers from loopback and private addresses, so
keep `HTTP_PORT` reachable by the proxy alone (the default `BIND_ADDRESS` is
`127.0.0.1`).

## Your own database or file store

Both bundled pieces are optional, each switched in the env file:

| | Default | Bring your own |
|---|---|---|
| Database | bundled PostgreSQL 17 (`COMPOSE_PROFILES=db`), volume `db-data` | any PostgreSQL 14+: empty `COMPOSE_PROFILES`, `DB_*` pointing at it |
| Documents | Docker volume `media` (`DJANGO_STORAGE_BACKEND=filesystem`), served only to logged-in users | any S3-compatible store: `DJANGO_STORAGE_BACKEND=s3` and `S3_*` (AWS S3, Cloudflare R2, Backblaze B2, Garage, SeaweedFS, …) |

For your own PostgreSQL, create once, as an administrator:

```sql
create role partitario_app login password '<database password>';
create database partitario owner partitario_app;
```

Django creates its schema and tables itself. A Postgres or S3 service running
on the same machine is reachable from the containers as
`host.docker.internal`. An S3 bucket must be **private**, and its endpoint
reachable from your browser too, because download links point straight at it.

## A faster cache (optional)

The cache is a table in the database by default, which needs nothing. A
project that caches for speed can start the bundled Valkey (Redis-compatible,
in memory, not published, nothing persisted) from the env file:

```
COMPOSE_PROFILES=db,cache
DJANGO_CACHE_URL=redis://cache:6379/0
```

or point `DJANGO_CACHE_URL` at a Redis of your own. See
[architecture.md](architecture.md#cache).

## Upgrades and backups

- **Upgrade:** change `PARTITARIO_VERSION` in the env file (or pull the new
  code) and run `up` again; pending database migrations are applied on start.
- **Backup:** `make selfhost-backup` writes a database dump, and an archive of
  the documents volume when they are stored on disk, into `backups/`. The two
  volumes are yours to back up; there is no restore target, a dump is restored
  with `pg_restore`.
