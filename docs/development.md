# Development

The [dev quickstart](../README.md#dev-quickstart) gets a server running. This
page covers what comes after. Every target is described in
[makefile.md](makefile.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker (the dev server, the local Supabase stack, the tests and the hadolint hook run in containers)
- GNU gettext (`apt install gettext` / `brew install gettext`), to compile the translations

Node.js is not needed: Tailwind runs inside the images.
- [Supabase CLI](https://supabase.com/docs/guides/cli/getting-started) 2.121.0 or later (one local project per worktree: see [worktrees.md](worktrees.md))

## What `make setup` does

| Step                   | Command                              | Result                                                    |
|------------------------|--------------------------------------|-----------------------------------------------------------|
| `make install`         | `uv sync`                            | Python dependencies (lint, tests, `manage.py` on the host) |
| `make hooks`           | `pre-commit install`                 | Git hooks (see below)                                     |
| `make supabase-start`  | `supabase start`                     | The local Supabase project of this worktree, on ports chosen by the CLI; role `partitario_app`, schema, bucket |
| `make env`             | `scripts/worktree-env.sh`            | `.env` from `.env.example`, with the ports of that project and the dev port (your own edits are never touched) |
| `make migrate`         | `manage.py migrate`                  | Tables in schema `partitario`, RLS enabled on each       |
| `make superuser`       | `manage.py ensure_superuser`         | Admin user from `.env` (idempotent, never modifies an existing user) |
| `make compilemessages` | `manage.py compilemessages`          | Italian translation compiled to `.mo`                     |
| `make check`           | `manage.py check` + `check_services` | Schema, RLS, and a private, writable bucket               |

The last line printed is the address of the dev server:
`http://localhost:8100/admin/` in the primary checkout. `make worktree-info`
prints it again, with the database port and the Supabase API URL;
`supabase status` shows everything else (Studio, keys).

## The development server

```bash
make worktree-up      # start Supabase, refresh .env, start the dev server; returns when it is ready
make worktree-info    # where it is running
make worktree-logs    # follow the server log (mail and confirmation links are printed there)
make worktree-down    # when done: close everything, data is kept
```

The dev server runs in Docker only, detached: Django's `runserver` and a
Tailwind watcher, with the source folders of the checkout mounted into them.
A change to Python, a template or the stylesheet is live; after a change to
`uv.lock` or the translations run `make worktree-up` again, which rebuilds
the image. In the main checkout it serves on port 8100.

## Parallel worktrees

Every git worktree, and every project created from the same template, runs
its own stack side by side: its own Supabase project, `.env`, dev server on
its own port, and cookies. In a new worktree:

```bash
make install worktree-up
```

How names and ports are chosen, what is live in the container, how to list
and clean up stacks, and why it was built this way:
[worktrees.md](worktrees.md).

## Everyday commands

```bash
make lint           # ruff check + format check, app dependency direction (import-linter)
make format         # ruff autofix + format
make typecheck      # mypy with django-stubs
make test           # pytest on a throwaway PostgreSQL container (Docker only, no Supabase)
make test-supabase  # the same suite on the local Supabase database
make smoke          # build the images, run the real stack, check it from the outside
make hooks-run      # every git hook on every file
make secrets        # gitleaks over the whole git history (Docker)
make db-reset       # wipe this worktree's local database and rebuild it from migrations
make backup         # dump this worktree's local database schema into backups/ (gitignored)
```

`typecheck` and `test` load the settings, so they need a `.env` (`make setup`
writes it; on a fresh clone `cp .env.example .env` is enough, as in CI).
`lint` and `smoke` need none.

`make test ARGS="-k rls"` passes arguments to pytest. Commands that are not
make targets run from `django/`, e.g. `cd django && uv run manage.py makemigrations`.

`make smoke` starts the self-hosted stack with the TLS front switched on and
verifies what unit tests cannot: redirects, unknown hosts, TLS versions,
security headers, the single login page and its rate limit, private documents, the readiness
healthcheck, the compiled translations and the content of the image. Run it
after touching `docker/`, nginx or HTTP-related settings, and add a check
there for what you changed.

## Git hooks

`make setup` installs the hooks of `.config/pre-commit.yaml`
([pre-commit](https://pre-commit.com)). A commit is refused if it adds a
spreadsheet, a dump, a key or an `.env` file, if
[gitleaks](https://github.com/gitleaks/gitleaks) finds a secret in it, or if
ruff, mypy, shellcheck or hadolint complain.

- pre-commit installs the tools itself (hadolint runs from its Docker image),
  so no check is skipped on a machine that lacks one. The hooks run on
  developer machines only, not in CI (see below).
- The settings live in `.config/`, so run the hooks through `make hooks-run`;
  a bare `pre-commit run` needs `-c .config/pre-commit.yaml`.
- The public keys of the local Supabase stack in `.env.example` are
  allowlisted in `.config/gitleaks.toml`.
- Hook versions are pinned: bump them with
  `pre-commit autoupdate -c .config/pre-commit.yaml`.

## Translations

Source strings are English, wrapped in `gettext`; the interface is Italian by
default (`LANGUAGE_CODE`) through `django/locale/it/LC_MESSAGES/django.po`.

```bash
make messages          # extract new strings into the .po file
# fill in the new msgstr entries
make compilemessages   # .po -> .mo
```

Compiled `.mo` files are not committed: the Docker image compiles them at
build time.

## Continuous integration and releases

`.gitlab/.gitlab-ci.yml` runs on merge requests and on the default branch, nothing
else. It is not in the place GitLab looks by default (the repository root), so
each project points GitLab at it once: Settings → CI/CD → General pipelines →
"CI/CD configuration file" = `.gitlab/.gitlab-ci.yml`. Without that setting no
pipeline starts, and GitLab reports no error. Each job calls the make target
you run locally:

| Job | Image | Runs |
|---|---|---|
| `lint-typecheck` | uv (Python 3.13) | `make lint typecheck` |
| `test` | uv + Docker CLI | `make test` (throwaway Postgres on the host's Docker) |
| `secrets` | gitleaks | `make secrets GITLEAKS=gitleaks GITLEAKS_REPO=.` (full history) |

The Python jobs copy `.env.example` to `.env`: the settings, and mypy's
Django plugin, need its development defaults (`make test` overrides `DB_*`).

It is written for a GitLab runner with the Docker executor, the host's Docker
socket and host networking, picked by the runner tag `local` (`default.tags`).
That tag is the one thing in the file a project on another runner must change. The
`secrets` job needs the `GITLEAKS` / `GITLEAKS_REPO` variables of
`make secrets`, set in its script.

On such a runner `/builds` is a Docker volume, so a container a job starts on
the host's Docker cannot mount the checkout: `docker run -v $PWD:...` mounts
an empty host directory and silently checks nothing. That is why `secrets`
runs inside the gitleaks image instead of starting it, and why the git hooks
are not in CI: hadolint runs from its own image the same way. ruff, mypy and
gitleaks already have their jobs, and every job costs a start on the runner;
shellcheck, hadolint and the check for committed data files run only on
commit, so run `make hooks-run` before pushing a change to a shell script or
the Dockerfile. Mounting `/builds` from the same path on the host (`builds_dir`
and `volumes` in the runner's `config.toml`) would lift that limit.

`make hooks-run`, `make smoke` and `make test-supabase` are not in CI: run them
locally. After changing `.gitlab/.gitlab-ci.yml`, run `make ci-lint` (glab 1.131.0 or
later: older releases such as 1.36.0, the Ubuntu package, fail with
`rate: Wait(n=1) exceeds limiter's burst 0`).

To publish a release, build the `production` and `nginx` targets of
`docker/Dockerfile` (the nginx one with `--build-context docker=docker`) for
`linux/amd64,linux/arm64`, and push them as `<image>:<version>` and
`<image>-nginx:<version>`. The stacks pull them when `PARTITARIO_IMAGE` and
`PARTITARIO_VERSION` are set in the env file.
