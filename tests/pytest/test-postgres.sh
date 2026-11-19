#!/bin/sh
# Run the test suite against a throwaway PostgreSQL container: nothing but
# Docker is needed, and no existing database is touched.
#
#   tests/pytest/test-postgres.sh [pytest arguments]   (make test ARGS="-k rls")
#
# The tests themselves live in django/apps/<app>/tests/; this is only the runner.
#
# The application only needs a plain PostgreSQL to be tested; file storage is
# swapped for memory by django/conftest.py. `make test-supabase` runs the same
# suite on the local Supabase stack instead.
set -eu

cd "$(dirname "$0")/../.."

IMAGE=${TEST_POSTGRES_IMAGE:-postgres:17-alpine}
# Unique per run (the process id): parallel runs never meet.
NAME=${PROJECT:-partitario}-test-$$

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

# Data in memory, a free port chosen by Docker, loopback only.
docker run -d --name "$NAME" --tmpfs /var/lib/postgresql/data \
    -e POSTGRES_PASSWORD=test -p 127.0.0.1::5432 "$IMAGE" >/dev/null
PORT=$(docker port "$NAME" 5432/tcp | head -1 | sed 's/.*://')

tries=0
until docker exec "$NAME" psql -U postgres -h 127.0.0.1 -c 'select 1' >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 60 ] || { echo "PostgreSQL did not start" >&2; exit 1; }
    sleep 0.5
done

# Real environment variables win over the values of .env (python-dotenv).
cd django
DB_HOST=127.0.0.1 DB_PORT="$PORT" DB_NAME=postgres DB_USER=postgres DB_PASSWORD=test \
    DB_SSLMODE=disable uv run pytest "$@"
