.DEFAULT_GOAL := help

# The project slug and its block of 100 ports for the Django dev server: the
# two values that tell this project apart from the others on the machine
# (docs/worktrees.md).
PROJECT       := partitario
DEV_PORT_BASE ?= 8100
export PROJECT DEV_PORT_BASE

# The Django project (pyproject.toml, package.json, manage.py) lives in django/.
DJANGO := cd django &&

# One identity per worktree, so that worktrees and projects run side by side:
# <PROJECT>-<branch>-<hash of the path>, stored in .env by `make env` and
# computed the same way without it (lint, test and smoke need no .env).
# Never write a container name or a local port here: derive them from these.
WORKTREE_ENV := scripts/worktree-env.sh
INSTANCE := $(shell $(WORKTREE_ENV) --instance)
# Read when a recipe runs, not when make starts: `make env` may just have set it.
DEV_PORT = $(shell $(WORKTREE_ENV) --port)
COMPOSE := docker compose -p $(INSTANCE) -f docker/compose.dev.yaml
.PHONY: help setup install env env-port supabase-start supabase-list \
        worktree-up worktree-down worktree-logs worktree-destroy worktree-info worktree-list worktree-prune \
        migrate superuser check messages compilemessages lint format typecheck \
        test test-supabase smoke \
        db-reset hooks hooks-run secrets backup \
        local-env local-push local-migrate local-superuser local-up local-down \
        local-check local-backup \
        staging-env staging-push staging-up staging-superuser staging-down staging-logs \
        staging-check staging-backup \
        prod-env prod-push prod-up prod-superuser prod-down prod-logs prod-check prod-backup \
        selfhost-env selfhost-up selfhost-superuser selfhost-down \
        selfhost-logs selfhost-check selfhost-backup

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- First run ----------------------------------------------------------------

# Supabase starts before the environment is generated: .env holds its ports.
setup: install hooks supabase-start env migrate superuser compilemessages check ## One-shot local bootstrap
	@echo "\nReady. Run 'make worktree-up' to start the dev server on http://localhost:$(DEV_PORT)/admin/"

env: ## Create or refresh .env for this worktree: ports of its Supabase project, dev port (never touches your edits)
	@$(WORKTREE_ENV)

env-port: ## Choose the Django dev port of this worktree again (when another process took it)
	@$(WORKTREE_ENV) --reset-port

# The configuration lives in .config/, not in the root: every call names it.
PRE_COMMIT := uv run --project django pre-commit
PRE_COMMIT_CONFIG := .config/pre-commit.yaml

hooks: ## Install the git hooks (pre-commit framework, .config/pre-commit.yaml)
	@git config --unset core.hooksPath || true
	$(PRE_COMMIT) install --config $(PRE_COMMIT_CONFIG)

hooks-run: ## Run every hook on every file, as CI does
	$(PRE_COMMIT) run --config $(PRE_COMMIT_CONFIG) --all-files

# The hook only sees what is being committed; this reads every commit.
GITLEAKS_IMAGE ?= ghcr.io/gitleaks/gitleaks:v8.30.1

secrets: ## Scan the whole git history for secrets (gitleaks, in Docker)
	docker run --rm -v "$(CURDIR):/repo:ro" $(GITLEAKS_IMAGE) git /repo \
		--config /repo/.config/gitleaks.toml --redact --no-banner

# Python only: the stylesheet is built inside the images (docker/Dockerfile).
install: ## Install the Python dependencies
	$(DJANGO) uv sync

# --- Supabase (local stack via the Supabase CLI) --------------------------------
# Stack mode (supabase/config.toml): every worktree and every branch has its own
# local project, on ports chosen by the CLI. Every command below acts on the
# project of this worktree only.

# Services to leave out, e.g. SUPABASE_EXCLUDE=rest,auth,studio,mail (the
# application needs the database and storage only).
SUPABASE_EXCLUDE ?=

supabase-start: ## Start the local Supabase project of this worktree (applies supabase/migrations on first start)
	@$(WORKTREE_ENV) --check-cli
	supabase start $(if $(SUPABASE_EXCLUDE),--exclude $(SUPABASE_EXCLUDE))

supabase-list: ## List every local Supabase project on this machine (all worktrees, all projects)
	supabase stack list

db-reset: ## DESTRUCTIVE: wipe this worktree's local DB, re-apply Supabase + Django migrations
	supabase db reset
	$(MAKE) migrate superuser

# --- Django -------------------------------------------------------------------

migrate: ## Apply Django migrations (also creates the schema and enables RLS)
	$(DJANGO) uv run manage.py migrate

superuser: ## Create the superuser from DJANGO_SUPERUSER_* (idempotent)
	$(DJANGO) uv run manage.py ensure_superuser

check: ## Verify DB schema, RLS on every table and the private bucket
	$(DJANGO) uv run manage.py check
	$(DJANGO) uv run manage.py check_services

# Source strings are English; Italian lives in django/locale/it. Both targets
# need GNU gettext (apt install gettext / brew install gettext).
messages: ## Extract translatable strings into django/locale/*/LC_MESSAGES/django.po
	$(DJANGO) uv run manage.py makemessages --all --ignore .venv --ignore node_modules --add-location file

compilemessages: ## Compile the translations (.po -> .mo, not committed)
	$(DJANGO) uv run manage.py compilemessages --ignore .venv --ignore node_modules

# --- Worktrees: one isolated stack each -------------------------------------------
# Nothing here reaches beyond this worktree: no `docker volume rm`, no
# `docker system prune`, no `supabase stack stop --all`.

# The only way to run the application in development: Supabase, then Django
# and the Tailwind watcher, both in Docker (docker/compose.dev.yaml). The
# source folders are mounted, so code, templates and CSS changes are live; it
# runs detached and returns once the server answers (or fails with its log).
# Run it again after a change to uv.lock or the translations: it rebuilds.
# No migrate / superuser here: the dev container runs both on start.
worktree-up: supabase-start env ## Start everything for this worktree and return when it is ready: Supabase, .env, dev server (live code and CSS)
	@$(WORKTREE_ENV) --preflight
	@$(COMPOSE) up --build --detach --wait || { $(COMPOSE) logs --tail 40; exit 1; }
	@echo "\nReady: http://localhost:$(DEV_PORT)/admin/   (log: make worktree-logs, stop: make worktree-down)"

worktree-logs: ## Follow the log of this worktree's dev server (mail and confirmation links are printed there)
	$(COMPOSE) logs --follow --tail 100

worktree-down: ## Close everything: remove this worktree's dev containers and stop its Supabase project (data is kept)
	$(COMPOSE) down
	supabase stop

# --volumes: the stylesheet volume of this compose project, nothing else.
worktree-destroy: ## DESTRUCTIVE: remove this worktree's dev containers, images and volume, smoke images and Supabase project with its data
	$(COMPOSE) down --rmi local --volumes --remove-orphans
	-docker image rm $(INSTANCE)-smoke:local $(INSTANCE)-smoke-nginx:local 2>/dev/null
	supabase stack destroy --yes

worktree-info: ## Show this worktree's instance name, application URL, database port and Supabase API URL
	@$(WORKTREE_ENV) --info

worktree-list: ## Every worktree of this repository: branch, URL, whether its dev server and Supabase run
	@$(WORKTREE_ENV) --list

# The one target that looks beyond this worktree, and only at what nobody owns.
worktree-prune: ## Remove what deleted worktrees left behind (containers, images, Supabase projects); asks first, YES=1 to skip
	@YES="$(YES)" $(WORKTREE_ENV) --prune

# --- Backups -------------------------------------------------------------------
# pg_dump of the app schema into backups/ (gitignored), through a throwaway
# postgres client container. $(1): env file, $(2): file name prefix.

# pg_dump must be at least as new as the server: override for a newer one,
# e.g. make selfhost-backup PG_CLIENT_IMAGE=postgres:18-alpine
PG_CLIENT_IMAGE ?= postgres:17-alpine

define db_backup
	@mkdir -p backups
	docker run --rm --network host --user $$(id -u):$$(id -g) --env-file $(1) \
		-v "$(CURDIR)/backups:/backups" $(PG_CLIENT_IMAGE) sh -c '\
		PGPASSWORD="$$DB_PASSWORD" PGSSLMODE="$$DB_SSLMODE" pg_dump \
			-h "$$DB_HOST" -p "$$DB_PORT" -U "$$DB_USER" \
			-d "$$DB_NAME" -n "$$DB_SCHEMA" --format=custom --no-owner \
			-f "/backups/$(2)-$$(date +%Y%m%d-%H%M%S).dump"'
	@ls -1t backups/$(2)-*.dump | head -1
endef

backup: ## Dump this worktree's local database schema into backups/
	$(call db_backup,.env,dev)

# --- Hosted environments (nginx + Django in Docker) ------------------------------
# staging / prod: docker/compose.staging.yaml and compose.prod.yaml, the same
# stack for a single-purpose server (nginx with TLS, certbot), each on its own
# Supabase project. selfhost: docker/compose.selfhost.yaml, plain HTTP behind
# the reverse proxy of the machine, on any PostgreSQL and S3 store. The env file .env.<env> is also passed to
# compose itself, which reads the host name and the ports from it.

# Which images run: PARTITARIO_VERSION in the env file names a published release
# to pull (CI publishes one on every v* tag); without it they are built
# from this checkout.
hosted_version = $(shell sed -n 's/^PARTITARIO_VERSION=//p' .env.$(1) 2>/dev/null)

# selfhost only: its compose file carries no build instructions (it also works
# without the repository), so they are merged in when building; and
# docker/compose.override.yaml (gitignored) is merged when it exists.
hosted_selfhost_files = $(if $(call hosted_version,selfhost),,-f docker/compose.selfhost.build.yaml) \
	$(addprefix -f ,$(wildcard docker/compose.override.yaml))
hosted_compose = ENV_FILE=../.env.$(1) docker compose --env-file .env.$(1) -f docker/compose.$(1).yaml \
	$(if $(filter selfhost,$(1)),$(hosted_selfhost_files))
hosted_ref = $(shell sed -n 's/^SUPABASE_PROJECT_REF=//p' .env.$(1) 2>/dev/null)

# $(2): template, .env.hosted.example unless given
define hosted_env
	@test -f .env.$(1) || (cp $(or $(2),.env.hosted.example) .env.$(1) && chmod 600 .env.$(1) && \
		echo "Created .env.$(1) from $(or $(2),.env.hosted.example) - fill it in")
endef

define hosted_require_env
	@test -f .env.$(1) || (echo "Missing .env.$(1) - run 'make $(1)-env' and fill it in" && exit 1)
endef

# Production holds the real data: ask before touching it.
# Non-interactive use: make prod-up CONFIRM=prod
define confirm_prod
	@if [ "$(CONFIRM)" != "prod" ]; then \
		printf "This acts on PRODUCTION. Type 'prod' to continue: "; \
		read answer; [ "$$answer" = "prod" ] || (echo "Aborted." && exit 1); \
	fi
endef

# DRY=1 previews: make staging-push DRY=1
define hosted_push
	$(call hosted_require_env,$(1))
	@case "$(call hosted_ref,$(1))" in ""|*"<"*) \
		echo "Set SUPABASE_PROJECT_REF in .env.$(1)" && exit 1;; esac
	@echo "Supabase migrations -> $(1) project $(call hosted_ref,$(1))"
	supabase db push --remote=$(call hosted_ref,$(1)) $(if $(DRY),--dry-run)
endef

# Interactive on purpose: the password is typed, validated and never stored.
define hosted_superuser
	$(call hosted_require_env,$(1))
	$(call hosted_compose,$(1)) run --rm web python manage.py createsuperuser
endef

define hosted_up
	$(call hosted_require_env,$(1))
	$(call hosted_compose,$(1)) up $(if $(call hosted_version,$(1)),--pull always --no-build,--build) --detach
	@echo "Started. Follow the first boot with 'make $(1)-logs'."
endef

staging-env: ## Create .env.staging from .env.hosted.example (never overwrites)
	$(call hosted_env,staging)

staging-push: ## Apply supabase/migrations to the staging project (DRY=1 to preview)
	$(call hosted_push,staging)

staging-up: ## Build and start staging (nginx + TLS, gunicorn, certbot)
	$(call hosted_up,staging)

staging-superuser: ## Create the staging admin user (interactive, password is not stored)
	$(call hosted_superuser,staging)

staging-down: ## Stop the staging containers (hosted data and certificates are kept)
	$(call hosted_compose,staging) down

staging-logs: ## Follow the staging logs
	$(call hosted_compose,staging) logs --follow

staging-check: ## Verify schema, RLS and bucket on the staging project
	$(call hosted_compose,staging) run --rm web python manage.py check_services

staging-backup: ## Dump the staging database schema into backups/
	$(call hosted_require_env,staging)
	$(call db_backup,.env.staging,staging)

prod-env: ## Create .env.prod from .env.hosted.example (never overwrites)
	$(call hosted_env,prod)

prod-push: ## Apply supabase/migrations to the production project (asks first; DRY=1 to preview)
	$(if $(DRY),,$(call confirm_prod))
	$(call hosted_push,prod)

prod-up: ## Build and start production (asks first)
	$(call confirm_prod)
	$(call hosted_up,prod)

prod-superuser: ## Create the production admin user (interactive, asks first)
	$(call confirm_prod)
	$(call hosted_superuser,prod)

prod-down: ## Stop the production containers (hosted data and certificates are kept)
	$(call hosted_compose,prod) down

prod-logs: ## Follow the production logs
	$(call hosted_compose,prod) logs --follow

prod-check: ## Verify schema, RLS and bucket on the production project
	$(call hosted_compose,prod) run --rm web python manage.py check_services

prod-backup: ## Dump the production database schema into backups/
	$(call hosted_require_env,prod)
	$(call db_backup,.env.prod,prod)

# selfhost is not tied to Supabase: any PostgreSQL and any S3-compatible store,
# configured in .env.selfhost. There is no `push`: Django creates its schema.

# In a clone the images are built locally (empty PARTITARIO_VERSION) and the
# secrets are generated; only the host name is left to fill in.
# No `sed -i`: its syntax differs between GNU (Linux) and BSD (macOS).
selfhost-env: ## Create .env.selfhost with generated secrets (never overwrites)
	@test -f .env.selfhost || { cp .env.selfhost.example .env.selfhost && chmod 600 .env.selfhost && \
		sed -e "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$$(openssl rand -hex 32)|" \
			-e "s|^DB_PASSWORD=.*|DB_PASSWORD=$$(openssl rand -hex 24)|" \
			-e "s|^PARTITARIO_IMAGE=.*|PARTITARIO_IMAGE=|" \
			-e "s|^PARTITARIO_VERSION=.*|PARTITARIO_VERSION=|" .env.selfhost > .env.selfhost.tmp && \
			cat .env.selfhost.tmp > .env.selfhost && rm .env.selfhost.tmp && \
		echo "Created .env.selfhost with generated secrets - set DJANGO_ALLOWED_HOSTS and the Turnstile keys in it"; }

selfhost-up: ## Start the self-hosted stack (bundled Postgres by default; behind your reverse proxy)
	$(call hosted_up,selfhost)

selfhost-superuser: ## Create the self-hosted admin user (interactive, password is not stored)
	$(call hosted_superuser,selfhost)

selfhost-down: ## Stop the self-hosted containers (database and documents are kept)
	$(call hosted_compose,selfhost) down

selfhost-logs: ## Follow the self-hosted logs
	$(call hosted_compose,selfhost) logs --follow

selfhost-check: ## Verify the database schema, RLS and the document storage of the self-hosted stack
	$(call hosted_compose,selfhost) run --rm web python manage.py check_services

# Bundled database: dumped from inside its container (it is not published).
define selfhost_bundled_backup
	@mkdir -p backups
	@f=backups/selfhost-$$(date +%Y%m%d-%H%M%S).dump; \
		$(call hosted_compose,selfhost) exec -T db sh -c \
			'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --format=custom --no-owner' > $$f && echo $$f
endef

selfhost_setting = $(shell sed -n 's/^$(1)=//p' .env.selfhost 2>/dev/null)

selfhost-backup: ## Dump the self-hosted database (and the documents volume) into backups/
	$(call hosted_require_env,selfhost)
	$(if $(findstring db,$(call selfhost_setting,COMPOSE_PROFILES)),$(selfhost_bundled_backup),$(call db_backup,.env.selfhost,selfhost))
	@if [ "$(call selfhost_setting,DJANGO_STORAGE_BACKEND)" = "filesystem" ]; then \
		f=backups/selfhost-media-$$(date +%Y%m%d-%H%M%S).tar.gz; \
		$(call hosted_compose,selfhost) run --rm --no-deps -T web tar -czf - -C /data media > $$f && echo $$f; \
	fi

# --- Local: the interface on this machine, the data in the cloud ------------------
# Personal use: Django in Docker on 127.0.0.1 only, on top of the hosted Supabase
# project of .env.local, which holds the real data. Not the development
# environment (that is `make worktree-up`, on the local Supabase stack).

# .env.local is also passed to compose itself, which reads LOCAL_PORT from it.
LOCAL_COMPOSE := docker compose $(addprefix --env-file ,$(wildcard .env.local)) -f docker/compose.local.yaml

local-env: ## Create .env.local from .env.hosted.example (never overwrites)
	$(call hosted_env,local)

local-push: ## First time: create the role, schema and bucket on the project of .env.local (DRY=1 to preview)
	$(call hosted_push,local)

local-migrate: ## Create or update the tables on the project of .env.local
	$(call hosted_require_env,local)
	$(LOCAL_COMPOSE) run --rm --build web python manage.py migrate

local-superuser: ## First time: create your user (interactive, password is not stored)
	$(call hosted_require_env,local)
	$(LOCAL_COMPOSE) run --rm web python manage.py createsuperuser

local-up: ## Run the interface locally on the cloud database: http://localhost:8003/admin/ (LOCAL_PORT)
	$(call hosted_require_env,local)
	$(LOCAL_COMPOSE) up --build --watch

local-down: ## Stop the local container (the data stays in the cloud)
	$(LOCAL_COMPOSE) down

local-check: ## Verify schema, RLS and bucket on the project of .env.local
	$(call hosted_require_env,local)
	$(LOCAL_COMPOSE) run --rm web python manage.py check_services

local-backup: ## Dump the database schema of the project of .env.local into backups/
	$(call hosted_require_env,local)
	$(call db_backup,.env.local,local)

# --- Quality ------------------------------------------------------------------

lint: ## Ruff lint + format check, app dependency direction (import-linter)
	$(DJANGO) uv run ruff check .
	$(DJANGO) uv run ruff format --check .
	$(DJANGO) uv run lint-imports

typecheck: ## mypy with django-stubs
	$(DJANGO) uv run mypy

format: ## Ruff autofix + format
	$(DJANGO) uv run ruff check --fix .
	$(DJANGO) uv run ruff format .

test: ## Run the test suite on a throwaway PostgreSQL container (no Supabase needed)
	tests/pytest/test-postgres.sh $(ARGS)

test-supabase: ## Run the test suite on this worktree's local Supabase database (.env)
	$(DJANGO) uv run pytest $(ARGS)

smoke: ## Build the images and exercise the real stack end to end (nginx, TLS, storage)
	tests/smoke/smoke.sh
