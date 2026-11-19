#!/bin/sh
# The identity and the .env of this worktree, so that several worktrees of one
# project, and several projects, run their development stacks side by side
# (docs/worktrees.md).
#
#   scripts/worktree-env.sh               (make env) create or refresh .env
#   scripts/worktree-env.sh --reset-port  (make env-port) choose the dev port again
#   scripts/worktree-env.sh --instance    print the name of this worktree's stack
#   scripts/worktree-env.sh --port        print the port of its Django dev server
#   scripts/worktree-env.sh --preflight   is that port ours to use?
#   scripts/worktree-env.sh --check-cli   is the Supabase CLI recent enough?
#   scripts/worktree-env.sh --info        (make worktree-info)
#   scripts/worktree-env.sh --list        (make worktree-list) every worktree's stack
#   scripts/worktree-env.sh --prune       (make worktree-prune) remove what deleted worktrees left
#
# .env is created from .env.example (in a new worktree, with the values you
# changed in the main checkout's .env); afterwards only the managed keys change:
#   WORKTREE_INSTANCE, DJANGO_DEV_PORT   written once
#   DB_HOST, DB_PORT, S3_ENDPOINT_URL    refreshed from the running local
#                                        Supabase project on every run
# Every other line stays as the user wrote it.
set -eu

cd "$(dirname "$0")/.."

SUPABASE_MIN_VERSION=2.121.0
ENV_FILE=.env

# PROJECT and DEV_PORT_BASE are defined once, at the top of the Makefile, which
# exports them; read from there when the script is run by hand.
makefile_var() { sed -n "s/^$1[[:space:]]*[:?]*=[[:space:]]*//p" Makefile | head -1; }
PROJECT=${PROJECT:-$(makefile_var PROJECT)}
DEV_PORT_BASE=${DEV_PORT_BASE:-$(makefile_var DEV_PORT_BASE)}
DEV_PORT_BASE=${DEV_PORT_BASE:-8000}

die() { echo "$*" >&2; exit 1; }

# --- .env -----------------------------------------------------------------------

# file_key <file> <key>: its value there, empty when the key or the file is missing.
file_key() {
    [ -f "$1" ] || return 0
    sed -n "s/^$2=//p" "$1" | head -1
}

# get_key <key>: its value in the .env of this worktree.
get_key() { file_key "$ENV_FILE" "$1"; }

# set_key <key> <value>: replace the line of the key, or append it. Nothing is
# written when the value is already there. No `sed -i`: GNU and BSD differ.
set_key() {
    [ "$(get_key "$1")" = "$2" ] && grep -q "^$1=" "$ENV_FILE" && return 0
    tmp=$(mktemp)
    # Through the environment: `awk -v` would interpret backslashes in a value.
    KEY="$1" VALUE="$2" awk '
        BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"] }
        index($0, key "=") == 1 && !done { print key "=" value; done = 1; next }
        { print }
        END { if (!done) print key "=" value }' "$ENV_FILE" >"$tmp"
    cat "$tmp" >"$ENV_FILE"
    rm -f "$tmp"
    echo "  $1=$2"
}

# --- Worktrees of this repository ---------------------------------------------------

# The path of every worktree, the main checkout first, this one included.
worktree_paths() { git worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p'; }

# Two `make env` at once (agents starting in parallel) must not pick the same
# port: one at a time, for the whole repository.
lock() {
    common=$(git rev-parse --git-common-dir 2>/dev/null) || return 0
    LOCK="$common/worktree-env.lock"
    tries=0
    until mkdir "$LOCK" 2>/dev/null; do
        tries=$((tries + 1))
        [ "$tries" -lt 150 ] ||
            die "Another 'make env' holds $LOCK. If none is running, remove that directory."
        sleep 0.2
    done
    trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
    trap 'exit 130' INT TERM
}

# A new worktree starts from .env.example plus what you changed by hand in the
# main checkout's .env (passwords, keys, flags), never its ports or its name.
inherit_env() {
    main=$(worktree_paths | head -1)
    [ -n "$main" ] && [ "$main" != "$(pwd -P)" ] && [ -f "$main/.env" ] || return 0
    grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$main/.env" | while IFS= read -r line; do
        key=${line%%=*}
        case "$key" in
            WORKTREE_INSTANCE | DJANGO_DEV_PORT | DB_HOST | DB_PORT | S3_ENDPOINT_URL) continue ;;
        esac
        set_key "$key" "${line#*=}" >/dev/null
    done
    echo "  with your settings from $main/.env"
}

# --- Identity ---------------------------------------------------------------------

# The current branch, lowercase, anything outside [a-z0-9] turned into "-", at
# most 40 characters; the short commit SHA on a detached HEAD.
branch_slug() {
    branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null) ||
        branch=$(git rev-parse --short HEAD 2>/dev/null) || branch=nogit
    printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | cut -c1-40 |
        sed 's/-*$//'
}

# <PROJECT>-<branch-slug>-<hash4>: the hash of the worktree's path keeps two
# clones of one project on the same branch apart.
compute_instance() {
    hash4=$(printf '%04x' $(($(printf '%s' "$(pwd -P)" | cksum | cut -d' ' -f1) % 65536)))
    printf '%s-%s-%s\n' "$PROJECT" "$(branch_slug)" "$hash4"
}

# Never recomputed once stored: renaming the branch must not orphan a stack.
instance() {
    stored=$(get_key WORKTREE_INSTANCE)
    if [ -n "$stored" ]; then echo "$stored"; else compute_instance; fi
}

# --- Django dev port ----------------------------------------------------------------

# Only "connection refused" (curl exit 7) means nobody is listening.
port_in_use() {
    rc=0
    curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1/" || rc=$?
    [ "$rc" -ne 7 ]
}

# The ports the other worktrees of this repository were given: theirs even
# while their stack is stopped. Their .env is the only record; a removed
# worktree frees its port by disappearing.
reserved_ports() {
    here=$(pwd -P)
    worktree_paths | while IFS= read -r path; do
        [ "$path" = "$here" ] || file_key "$path/.env" DJANGO_DEV_PORT
    done
}

# DEV_PORT_BASE + the number of a branch named like lab-12-invoice-form (mod
# 100), DEV_PORT_BASE otherwise; then the next port of the project's block of
# 100 that no other worktree holds and nobody listens on, wrapping around.
choose_port() {
    reserved=" $(reserved_ports | tr '\n' ' ') "
    number=$(branch_slug | sed -n 's/^[a-z][a-z]*-\([0-9][0-9]*\)-.*/\1/p' | cut -c1-9)
    offset=$((${number:-0} % 100))
    tries=0
    while [ "$tries" -lt 100 ]; do
        candidate=$((DEV_PORT_BASE + (offset + tries) % 100))
        tries=$((tries + 1))
        case "$reserved" in *" $candidate "*) continue ;; esac
        if ! port_in_use "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    die "No free port between $DEV_PORT_BASE and $((DEV_PORT_BASE + 99)): remove a worktree," \
        "or give this project another block (DEV_PORT_BASE in the Makefile)."
}

dev_port() {
    stored=$(get_key DJANGO_DEV_PORT)
    echo "${stored:-$DEV_PORT_BASE}"
}

# Is the Docker dev server of this worktree the one running?
own_container_running() {
    [ -n "$(docker compose -p "$(instance)" -f docker/compose.dev.yaml ps -q --status running web-dev 2>/dev/null)" ]
}

# The other worktrees of this repository never get this port (reserved_ports),
# but a process outside it may have taken it while this stack was stopped.
preflight() {
    port=$(dev_port)
    port_in_use "$port" || return 0
    own_container_running && return 0
    die "Port $port is in use by another process. Run 'make env-port' to pick a new one."
}

# --- Supabase ---------------------------------------------------------------------

check_cli() {
    command -v supabase >/dev/null 2>&1 ||
        die "The Supabase CLI is not installed: https://supabase.com/docs/guides/cli/getting-started"
    version=$(supabase --version 2>/dev/null | sed -n 's/^v\{0,1\}\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)
    newest=$(printf '%s\n%s\n' "$SUPABASE_MIN_VERSION" "$version" |
        sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
    if [ -z "$version" ] || [ "$newest" != "$version" ]; then
        die "Supabase CLI ${version:-(unknown version)} is too old: $SUPABASE_MIN_VERSION or later is needed" \
            "(one local project per worktree). Update it:" \
            "https://supabase.com/docs/guides/cli/getting-started#updating-the-supabase-cli"
    fi
}

# status_value <NAME>: a variable of the running local project of this worktree.
supabase_status() { supabase status --env --output-format text 2>/dev/null || true; }
status_value() { echo "$STATUS" | sed -n "s/^$1=//p" | head -1 | tr -d "'\""; }

refresh_supabase() {
    check_cli
    STATUS=$(supabase_status)
    db_url=$(status_value DB_URL)
    api_url=$(status_value API_URL)
    if [ -z "$db_url" ] || [ -z "$api_url" ]; then
        die "The local Supabase project of this worktree is not running: run 'make supabase-start'," \
            "then 'make env' again. (Branch renamed? 'make supabase-list' shows the project of the old name.)"
    fi
    # postgresql://user:password@host:port/database
    address=${db_url#*@}
    address=${address%%/*}
    set_key DB_HOST "${address%:*}"
    set_key DB_PORT "${address##*:}"
    set_key S3_ENDPOINT_URL "${api_url%/}/storage/v1/s3"
}

# --- Commands -----------------------------------------------------------------------

generate() { # generate [--reset-port]
    lock
    if [ ! -f "$ENV_FILE" ]; then
        cp .env.example "$ENV_FILE"
        echo "Created .env from .env.example"
        inherit_env
    fi
    [ -n "$(get_key WORKTREE_INSTANCE)" ] || set_key WORKTREE_INSTANCE "$(compute_instance)"
    if [ "${1:-}" = --reset-port ]; then
        # The Docker dev server of this worktree would count as "in use".
        if own_container_running; then
            die "Stop this worktree's dev server first: make worktree-down"
        fi
        port=$(choose_port)
        set_key DJANGO_DEV_PORT "$port"
        return 0
    fi
    if [ -z "$(get_key DJANGO_DEV_PORT)" ]; then
        port=$(choose_port)
        set_key DJANGO_DEV_PORT "$port"
    fi
    refresh_supabase
}

info() {
    echo "Instance:      $(instance)"
    echo "Application:   http://localhost:$(dev_port)/admin/"
    echo "Database:      $(get_key DB_HOST):$(get_key DB_PORT)"
    echo "Supabase API:  $(get_key S3_ENDPOINT_URL | sed 's|/storage/v1/s3$||')"
    [ -n "$(get_key WORKTREE_INSTANCE)" ] || echo "(no generated .env yet: run 'make env')"
}

# --- Every worktree: list, prune ----------------------------------------------------

# One line per local Supabase project of the machine: id, root, branch, owner.
supabase_stacks() {
    supabase stack list --output-format json 2>/dev/null | tr '{' '\n' |
        sed -n 's/.*"id":"\([^"]*\)","project_root":"\([^"]*\)".*"branch_context":"\([^"]*\)".*"owner":"\([^"]*\)".*/\1|\2|\3|\4/p'
}

list() {
    stacks=$(supabase_stacks)
    printf '%-32s %-34s %-5s %-9s %s\n' BRANCH APPLICATION DEV SUPABASE PATH
    worktree_paths | while IFS= read -r path; do
        if [ ! -d "$path" ]; then
            printf '%-32s %-34s %-5s %-9s %s\n' "?" "-" "-" "-" "$path (deleted: make worktree-prune)"
            continue
        fi
        if branch=$(git -C "$path" symbolic-ref --quiet --short HEAD 2>/dev/null); then
            context="refs/heads/$branch"
        else
            branch="(detached)"
            context=detached
        fi
        name=$(file_key "$path/.env" WORKTREE_INSTANCE)
        port=$(file_key "$path/.env" DJANGO_DEV_PORT)
        url="(no .env: make worktree-up)"
        dev=-
        if [ -n "$name" ]; then
            url="http://localhost:$port/admin/"
            dev=down
            [ -z "$(docker ps -q --filter "label=com.docker.compose.project=$name" \
                --filter label=com.docker.compose.service=web-dev 2>/dev/null)" ] || dev=up
        fi
        case "$(echo "$stacks" | grep -F "|$path|$context|" | head -1)" in
            "") supabase=- ;;
            *"|reachable") supabase=up ;;
            *) supabase=down ;;
        esac
        printf '%-32s %-34s %-5s %-9s %s\n' "$branch" "$url" "$dev" "$supabase" "$path"
    done
}

# Compose projects of this project found on the machine: containers, volumes
# and images, the smoke ones folded into their instance.
docker_instances() {
    {
        docker ps -a --filter label=com.docker.compose.project \
            --format '{{.Label "com.docker.compose.project"}}'
        docker volume ls --filter label=com.docker.compose.project \
            --format '{{.Label "com.docker.compose.project"}}'
        docker images --format '{{.Repository}}' |
            sed -n -e 's/-web-dev$//p' -e 's/-css-dev$//p' -e 's/-smoke-nginx$//p' -e 's/-smoke$//p'
    } 2>/dev/null | sed 's/-smoke$//' | grep "^$PROJECT-..*-[0-9a-f]\{4\}$" | sort -u
}

# Does a container of this compose project still point at an existing directory?
# (Another clone of the project, not a worktree of this repository.)
instance_has_home() {
    docker ps -a --filter "label=com.docker.compose.project=$1" \
        --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null |
        while IFS= read -r dir; do
            [ -d "$dir" ] && echo yes
        done | grep -q yes
}

# What deleted worktrees left behind: local Supabase projects whose directory
# is gone (any project: nothing can reach them any more), and the dev and
# smoke containers, images and stylesheet volume of instances of THIS project
# that no worktree owns. Lists first, removes after a "yes" (or YES=1).
prune() {
    live=" $(worktree_paths | while IFS= read -r path; do file_key "$path/.env" WORKTREE_INSTANCE; done | tr '\n' ' ') $(instance) "
    gone_stacks=$(supabase_stacks | while IFS='|' read -r id root branch _; do
        [ -d "$root" ] || echo "$id|$root|$branch"
    done)
    gone_instances=$(docker_instances | while IFS= read -r name; do
        case "$live" in *" $name "*) continue ;; esac
        instance_has_home "$name" || echo "$name"
    done)
    if [ -z "$gone_stacks" ] && [ -z "$gone_instances" ]; then
        echo "Nothing to prune."
        return 0
    fi
    [ -z "$gone_stacks" ] || echo "$gone_stacks" | while IFS='|' read -r id root branch; do
        echo "Supabase project with its data: $root ($branch), directory deleted"
    done
    [ -z "$gone_instances" ] || echo "$gone_instances" | while IFS= read -r name; do
        echo "Containers, images and stylesheet volume: $name"
    done
    if [ "${YES:-}" != 1 ]; then
        printf "Remove them? Type 'yes' to continue: "
        read -r answer || answer=""
        [ "$answer" = yes ] || die "Aborted."
    fi
    [ -z "$gone_stacks" ] || echo "$gone_stacks" | while IFS='|' read -r id _ _; do
        supabase stack destroy --stack-id "$id" --yes >/dev/null 2>&1 &&
            echo "Removed Supabase project $id" || echo "Could not remove Supabase project $id" >&2
    done
    [ -z "$gone_instances" ] || echo "$gone_instances" | while IFS= read -r name; do
        # No compose file is left: compose finds the resources by project name.
        docker compose -p "$name" down --volumes --remove-orphans >/dev/null 2>&1 || true
        docker compose -p "$name-smoke" down --volumes --remove-orphans >/dev/null 2>&1 || true
        docker image rm "$name-web-dev" "$name-css-dev" "$name-smoke:local" \
            "$name-smoke-nginx:local" >/dev/null 2>&1 || true
        echo "Removed $name"
    done
    git worktree prune
}

case "${1:-}" in
    "") generate ;;
    --reset-port) generate --reset-port ;;
    --instance) instance ;;
    --port) dev_port ;;
    --preflight) preflight ;;
    --check-cli) check_cli ;;
    --info) info ;;
    --list) list ;;
    --prune) prune ;;
    *) die "Usage: $0 [--reset-port | --instance | --port | --preflight | --check-cli | --info | --list | --prune]" ;;
esac
