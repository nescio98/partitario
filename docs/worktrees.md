# Parallel worktrees

Several copies of the development stack run on one machine at the same time:
one per git worktree — coding agents working side by side, each on its own
branch — and one per project created from the same template. This page
records how that works and why it was built this way. The commands are also
in [makefile.md](makefile.md); the rest of the daily workflow is in
[development.md](development.md).

## Commands

| Command | What it does |
|---|---|
| `make install worktree-up` | In a new worktree: dependencies, then everything below |
| `make worktree-up` | Start this worktree's Supabase project, refresh `.env`, start the dev server; returns when it answers |
| `make worktree-info` | This worktree's instance name, application URL, database port, Supabase API URL |
| `make worktree-logs` | Follow the dev server log (mail and confirmation links are printed there) |
| `make worktree-list` | Every worktree of the repository: branch, URL, dev server and Supabase up or down |
| `make worktree-down` | Remove the dev containers and stop Supabase; data and ports are kept |
| `make worktree-destroy` | DESTRUCTIVE: containers, images, volume and the Supabase project with its data. Run it before `git worktree remove` |
| `make worktree-prune` | Remove what worktrees deleted without `worktree-destroy` left behind; lists first, then asks |
| `make env-port` | Choose the dev port again, when a process outside the repository took it |
| `make supabase-list` | Every local Supabase project on the machine |

```bash
git worktree add ../wt-8 -b lab-8-demo && cd ../wt-8
make install worktree-up     # http://localhost:8108/admin/
# ... work ...
make worktree-destroy && cd - && git worktree remove ../wt-8
```

## Decisions

### 1. One identity per stack

Every container, image, volume and compose project is named after the
*instance* of the worktree, never after a literal:

```
<PROJECT>-<branch-slug>-<hash4>      partitario-lab-12-add-invoice-form-3fa1
```

- `PROJECT`: the project slug, defined once at the top of the `Makefile`.
- `branch-slug`: the branch in lowercase, anything outside `[a-z0-9]` turned
  into `-`, 40 characters at most; the short commit SHA on a detached HEAD.
- `hash4`: four hex digits from the absolute path of the worktree. They keep
  two clones of one project on the same branch apart.

`scripts/worktree-env.sh` computes it once and stores it in `.env` as
`WORKTREE_INSTANCE`. It is not recomputed while `.env` exists, so renaming the
branch does not orphan running containers. Targets that need no `.env` (`lint`,
`test`, `smoke`, CI) compute the same value on the fly.

### 2. No fixed port

| Range | Assigned by | Used by |
|---|---|---|
| 20000 to 32767 | the Supabase CLI, stable per local project | database, API / storage, Studio |
| 32768 and above | Docker or the test scripts, per run | test database, smoke test |
| `DEV_PORT_BASE` to `DEV_PORT_BASE + 99` (8100 to 8199 here) | `scripts/worktree-env.sh`, stable per worktree | Django dev server |

**The dev port.** Each project declares a block of 100 ports in its `Makefile`
(`DEV_PORT_BASE`). Inside it a worktree gets `DEV_PORT_BASE` plus the number
of a branch named like `lab-12-add-invoice-form` (modulo 100), or
`DEV_PORT_BASE` itself when the branch has no number — the main checkout is
therefore on 8100. If that port is taken, the next free one of the block.

**The `.env` of each worktree is the record of its port.** The port is written
once as `DJANGO_DEV_PORT` and belongs to the worktree for as long as it
exists, running or stopped. `make env` reads the `.env` of every other
worktree (`git worktree list`) and never hands out a port one of them holds;
a lock in the shared `.git` directory makes two `make env` started together
wait for each other. So `lab-8-a` and `lab-8-b` get 8108 and 8109, in
either order, even when started at the same instant.

Why no registry file: it would be a second copy of what the `.env` files
already say, and it would have to be cleaned up. This way a removed worktree
frees its port by disappearing.

**What can still go wrong.** A process outside the repository can take the
port while the stack is stopped. `make worktree-up` checks first and stops
with `Port 8108 is in use by another process. Run 'make env-port' to pick a
new one.` — never with a raw "address already in use". Two *projects* that
declare the same block are not detected: the second one simply finds its
ports taken and moves to the next free ones.

### 3. One local Supabase project per worktree

`supabase/config.toml` enables the CLI's
[stack mode](https://supabase.com/docs/guides/local-development/running-multiple-local-projects)
(`stack = true` under `[experimental]`; Supabase CLI 2.121.0 or later, checked
by `make supabase-start`). The CLI identifies a local project by its project
root and git branch, and gives each one its own ports, database and storage.

- No port is written in `config.toml`: a port written there is used as
  written, and the second local project would fail to start.
- `project_id` does not have to be unique between projects.
- `supabase/migrations/` and `supabase/seed.sql` are applied on the first
  start of each local project: the role, the schema and the bucket exist.
- The application needs the database and storage only.
  `make supabase-start SUPABASE_EXCLUDE=rest,auth,studio,mail` leaves the
  rest out; services other than the database start on first request anyway.
- `supabase/supabase.lock` pins the versions of the Supabase services. The
  CLI writes it on the first start; it is committed.

### 4. `.env` belongs to the worktree

`make env` (`scripts/worktree-env.sh`) creates `.env` and afterwards changes
only the keys it manages; every other line stays as you wrote it. Running it
twice changes nothing.

| Key | Written | Source |
|---|---|---|
| `WORKTREE_INSTANCE` | once | decision 1 |
| `DJANGO_DEV_PORT` | once (`make env-port` chooses again) | decision 2 |
| `DB_HOST`, `DB_PORT` | every run | `DB_URL` of `supabase status` |
| `S3_ENDPOINT_URL` | every run | `API_URL` of `supabase status` + `/storage/v1/s3` |

The S3 key pair is not managed: it is the same public default in every local
project. `.env.example` keeps placeholders for the ports, so `cp .env.example
.env` (what CI does) still works without Supabase.

A new worktree does not start from scratch: its `.env` is `.env.example`
plus every value you changed in the `.env` of the main checkout — admin
password, keys, flags. Ports and the instance name are always its own.

### 5. The dev server runs in Docker only, on mounted source

There is one way to run the application in development, `make worktree-up`,
and nothing runs on the host: no `runserver`, no Node.js. The host keeps `uv`
for lint, tests and `manage.py` commands.

`docker/compose.dev.yaml` starts two containers from the production
Dockerfile:

- **`web-dev`**: Django's `runserver`. It applies pending migrations and
  creates the admin user when it starts.
- **`css-dev`**: Tailwind in watch mode. It rewrites the stylesheet whenever
  a template, a Python file or `tailwind/app.css` changes, into a volume the
  dev server reads. A new class in a template is in the page on the next
  reload.

**The source folders of the worktree are mounted into the containers, read
only.** What runs is always what is on disk. The first version copied changed
files into the containers with `docker compose watch`; that needs a process
in the foreground for as long as you work, and when it dies the containers
keep serving the code they last received, silently. With mounts there is no
such process, so the stack runs detached: `make worktree-up` returns once the
server answers its health check, or fails showing the server log. That is
what a coding agent needs: one command that ends and says whether it worked.

| Change | Live | Otherwise |
|---|---|---|
| Python in `apps/`, `config/`, `manage.py` | yes: the server reloads | |
| Templates | yes | |
| `tailwind/app.css`, classes used in templates and Python | yes: the watcher rebuilds | |
| Files in `static/` | yes | |
| `uv.lock`, `package-lock.json` (dependencies) | no | `make worktree-up` again: it rebuilds the image |
| `locale/` (translations) | no: they are compiled into the image | `make worktree-up` again |
| A new migration file | the file is there at once; it is applied at the next start | `make migrate`, or `make worktree-up` again |

Only source folders are mounted, never the whole of `django/`: its `.venv`
belongs to the host and would hide the one of the image.
`django/static/css/.gitkeep` keeps the mount point of the stylesheet volume in
every checkout, so Docker never creates it as root. The container user (uid
10001) must be able to read your files: with a restrictive `umask` (`077`)
the server cannot start.

`web-dev` uses host networking: it reads the same `.env` as the host and
reaches Supabase on `127.0.0.1`, which is also why signed storage URLs open
in the browser. On Docker Desktop, host networking must be enabled.

### 6. Loopback only

With host networking a server bound to `0.0.0.0` is on the local network. The
dev server runs with `DEBUG` on and the default admin password, so it listens
on `127.0.0.1` only. The Supabase CLI is different: it listens on every
interface, with public default credentials — development data only.

### 7. Cookies per dev server

Browsers do not separate cookies by port: logging in on `localhost:8108`
would log you out of `localhost:8109`. Under `DEBUG`, when `DJANGO_DEV_PORT`
is set, the session, CSRF and language cookies carry the port in their name
(`sessionid_8108`). Nothing changes in staging, production, selfhost or
`local-*`, whose env files do not set it. This is the only change in
`django/` for all of the above.

### 8. Cleaning up

- `make worktree-down` stops; data, ports and images stay.
- `make worktree-destroy` removes everything this worktree owns, and nothing
  else.
- `make worktree-prune` is for worktrees removed without it. It looks for
  what no existing worktree owns — local Supabase projects whose directory
  is gone (of any repository: nothing can reach them any more) and this
  project's dev and smoke containers, images and stylesheet volumes — lists
  it, and removes it after you type `yes` (`YES=1` skips the question).
- No target uses `docker volume rm`, `docker system prune` or
  `supabase stack stop --all`: they reach beyond the current worktree.

## What is unique, and at which level

| Resource | Name or value | Unique per |
|---|---|---|
| Supabase containers | `supabase-<directory>-<service>-<hash>` | worktree and branch |
| Supabase ports | chosen by the CLI | worktree and branch |
| Supabase data | a directory per local project inside one Docker volume (`supabase-db-<hash>`) shared by every local project of the machine: never remove that volume | worktree and branch |
| `.env` | `make env` | worktree |
| Dev compose project | `<instance>` | worktree |
| Dev containers | `<instance>-web-dev-1`, `<instance>-css-dev-1` | worktree |
| Dev images | `<instance>-web-dev`, `<instance>-css-dev` | worktree |
| Stylesheet volume | `<instance>_css` | worktree |
| Django dev port | `DJANGO_DEV_PORT` | worktree |
| Browser cookies | `sessionid_<port>`, `csrftoken_<port>` | dev server |
| Smoke compose project and images | `<instance>-smoke`, `<instance>-smoke[-nginx]:local` | worktree |
| Smoke ports | three free ports (or `SMOKE_HTTP_PORT`, `SMOKE_HTTP_TLS_PORT`, `SMOKE_HTTPS_PORT`) | run |
| Test database | container `partitario-test-<pid>`, port chosen by Docker | run |
| Personal `local-*` stack | `partitario-local`, port `LOCAL_PORT` of `.env.local` (8003) | project |
| Self-hosted stack | `partitario-selfhost`, `HTTP_PORT` of `.env.selfhost` | project |

Already safe, nothing to fix: the test database (unique per run), `make backup`
(reads this worktree's `.env`, writes to its `backups/`), the git hooks
(`.git/hooks` is shared by the worktrees of a repository on purpose, and
installing them is idempotent), `uv sync` (per directory, with a shared
download cache).

## Rules for coding agents

- In a new worktree: `make install worktree-up`. It returns when the server
  is ready; a non-zero exit means it is not, and the log is printed.
- Read the address from `make worktree-info`. Never assume a port.
- Stay in your worktree: never run another worktree's targets, never
  `make worktree-prune`, never edit `DJANGO_DEV_PORT` by hand.
- After changing `uv.lock` or a translation, run `make worktree-up` again.
- When the work is done: `make worktree-destroy`, then remove the worktree.

## Known limits

- **The local Supabase project follows the branch.** Renaming the branch, or
  switching branch inside a worktree, selects another (new, empty) local
  project, and the old one keeps running under its old name:
  `make supabase-list` shows it, `supabase stack destroy --stack-id <id>`
  removes it. Rename back, or run `make worktree-up` for the new name. The
  dev containers keep their name either way.
- A detached HEAD has a local project of its own, one per worktree.
- When another process holds a port of a stopped local Supabase project,
  `supabase start` fails naming the port; it does not pick another one.
- Stack mode is experimental: the CLI may change its flags and output. What
  the script reads from it is in one place (`supabase status --env`,
  `supabase stack list`).
- Flash messages use Django's `messages` cookie, whose name is not
  configurable: a message raised on one dev server may show up on another.
- A new worktree starts with an empty database (migrations and the admin
  user only): data is not copied from another worktree.
- Every worktree runs its own Postgres and two dev containers and builds its
  own images (layers are shared). Destroy the ones you no longer use.
- Isolation ends at merge time: two branches can still add a Django migration
  with the same number, or touch the same lines of `CHANGELOG.md`,
  `django.po` and `uv.lock`. Regenerate the migration after rebasing.

## Alternatives not taken

| Alternative | Why not |
|---|---|
| A machine-wide registry of ports | A second source of truth to keep clean; the `.env` files and `git worktree list` already hold it |
| Host names instead of ports (`<instance>.localhost` behind a local proxy) | One more always-on service; the port block and the cookie suffix are enough |
| A dev server on the host (`make dev`) | Two ways to run the same thing, and Node.js on the host for the stylesheet |
| `docker compose watch` (files copied into the containers) | Needs a foreground process; when it dies the containers serve stale code |
| One Docker daemon per worktree | Far heavier than naming things apart |
| Fixed Supabase ports per worktree | The CLI already assigns stable ones; written ports collide |
