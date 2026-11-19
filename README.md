# partitario

Ledger, tax and bank-account tracker for an Italian **partita IVA in regime
forfettario**: the web-app evolution of the `PartitaIva2026.xlsx` spreadsheet.

> **Status: infrastructure only.** Login, admin, storage, Docker stacks and
> tooling are in place. The ledger itself is not built yet: see
> [Roadmap](#roadmap) and [docs/domain.md](docs/domain.md).

## Dev quickstart

Everything runs in Docker: Django with live reload, and a local Supabase
project for the database and files. Needs [uv](https://docs.astral.sh/uv/),
Docker, the [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started)
(2.121.0 or later) and GNU gettext.

```bash
make setup           # once: dependencies, git hooks, Supabase, .env, database, admin user
make worktree-up     # start Supabase and the dev server; code, templates and CSS reload live
make worktree-info   # where it runs: http://localhost:8100/admin/ in the main checkout
make worktree-logs   # the server log
make worktree-down   # stop everything; the data is kept
```

Log in with `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` from
`.env`. Anybody else signs up at `/accounts/signup/`; there is no mail server
in development, so the confirmation link is printed in the server log.

Each git worktree is its own stack, on its own port: run
`make install worktree-up` in a new one
([docs/worktrees.md](docs/worktrees.md)).

## Local quickstart

The interface running on your machine, on top of a **cloud** database: a
hosted Supabase project holds the data and the files. This is not the
development environment (that is the dev quickstart above): it is how one
person uses the application without running a server. Needs Docker, the
Supabase CLI and a [prepared project](docs/deployment.md#preparing-a-supabase-project).

```bash
make local-env        # creates .env.local: fill it in
make local-push       # first time: role, schema and bucket on the project
make local-migrate    # first time, and after every update: the tables
make local-superuser  # first time: your login
make local-up         # http://localhost:8003/admin/
```

It listens on `127.0.0.1` only. To serve other people, use the self-hosted stack.

## Selfhost quickstart

The full stack on your own machine, behind the reverse proxy it already has.
It brings its own PostgreSQL and keeps documents in a volume. Needs Docker only.

```bash
make selfhost-env        # creates .env.selfhost: set DJANGO_ALLOWED_HOSTS and the Turnstile keys
make selfhost-up
make selfhost-superuser  # first time only
```

Then point your proxy (HTTPS) at `127.0.0.1:8080`:
[docs/selfhosting.md](docs/selfhosting.md).

## Documentation

| | |
|---|---|
| [docs/domain.md](docs/domain.md) | What the application must do, sheet by sheet |
| [docs/development.md](docs/development.md) | Daily workflow, tests, git hooks, translations |
| [docs/worktrees.md](docs/worktrees.md) | Parallel stacks for worktrees and agents: names, ports, `.env`, mounts, and why |
| [docs/deployment.md](docs/deployment.md) | Staging and production: Supabase, TLS, hardening |
| [docs/selfhosting.md](docs/selfhosting.md) | Reverse proxy, own Postgres or S3, upgrades, backups |
| [docs/architecture.md](docs/architecture.md) | Stack, layout, app boundaries, backing services |
| [docs/makefile.md](docs/makefile.md) | Every make target, by scenario |

## Roadmap

The application replaces each sheet of the spreadsheet with configurable data:

1. **Parametri fiscali per anno**: one tax configuration per fiscal year. A
   law change becomes a new configuration; closed years are never recomputed.
2. **Scadenze**: deadlines generated per year from the configuration,
   including the ones paid in the following year.
3. **Fatture**: invoices, with the document in the private store.
4. **Banche / broker**: each with one conto corrente and one conto titoli.
5. **Estratto conto**: derived from the movements of both, filterable by bank.
6. **Dashboard**: fatturato, soglia, tasse da accantonare, prossime scadenze.
