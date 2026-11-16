# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Parallel development stacks: every git worktree, and every project created
  from the template, runs its own local Supabase project, Django dev server
  and smoke test side by side. New targets `worktree-up`, `worktree-down`,
  `worktree-destroy`, `worktree-info`, `supabase-list`, `env-port`; new script
  `scripts/worktree-env.sh`.
- `PROJECT` and `DEV_PORT_BASE` at the top of the `Makefile`: the project slug
  and its block of 100 ports for the dev server.
- `LOCAL_PORT` in `.env.local`, for the port of `make local-up`.
- `make worktree-list` (every worktree with its URL and state) and
  `make worktree-prune` (what worktrees removed without `worktree-destroy`
  left behind).
- A worktree keeps its dev port while it exists, even stopped: `make env`
  skips the ports of the other worktrees and takes a lock, so parallel runs
  never pick the same one. A new worktree's `.env` starts with the values
  changed in the main checkout's.
- `docs/worktrees.md`: how parallel stacks work and why.
- `make worktree-logs`.
- `make worktree-up` runs a Tailwind watcher next to Django: template, Python
  and stylesheet changes are live without a second terminal or a rebuild.

### Changed
- The dev stack runs detached on mounted source folders instead of
  `docker compose watch`: `make worktree-up` returns when the server answers
  and fails with its log otherwise.
- The dev server listens on `127.0.0.1` only, no longer on every interface.
- The dev server runs in Docker only and Node.js is no longer needed on the
  host: `make install` is `uv sync`.
- `make worktree-up` no longer migrates on the host (the dev container does);
  `make worktree-down` is the one way to close everything.
- `make staging-push DRY=1` (also `prod-push`, `local-push`) previews the
  Supabase migrations.
- Local Supabase runs in the CLI's stack mode (Supabase CLI 2.121.0 or later):
  no port is set in `supabase/config.toml`, the CLI assigns them and
  `make env` writes them to `.env`. The local data of the previous fixed-port
  stack is not carried over: run `make setup` again.
- `make setup` starts Supabase before it generates `.env`; `make env` now
  refreshes the keys it manages instead of only copying `.env.example`.
- The dev server listens on `DJANGO_DEV_PORT` (8100 in the primary checkout)
  and, under `DEBUG`, suffixes its cookie names with it.
- `make smoke` uses a compose project and image names of its own per worktree
  and three free ports, unless `SMOKE_*_PORT` are set.

### Removed
- `make dev`, `docker-dev` (now part of `worktree-up`), `css`, `css-watch`,
  `docker-dev-down`, `supabase-stop`, `supabase-status`, `new-migration` and
  the three `*-push-dry` targets (see above for what replaces each).

## [v0.0.0] - 2026-11-16

### Added
- Initial release of partitario project
