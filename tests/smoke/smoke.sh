#!/bin/sh
# End-to-end smoke test: build the images, start the real self-hosted stack
# (bundled PostgreSQL, documents on disk) with the TLS front switched on, and
# check from the outside what unit tests cannot see - nginx, TLS, headers,
# the login rate limit, private documents, the task worker, the content of
# the image.
#
#   tests/smoke/smoke.sh        (make smoke)
#
# Needs Docker and curl only. Everything it creates is removed afterwards.
set -eu

cd "$(dirname "$0")/../.."

# One compose project and one image name per worktree (the same instance name
# as the dev stack, computed without .env when there is none): two worktrees,
# or two projects, run the smoke test at the same time.
INSTANCE=$(scripts/worktree-env.sh --instance)

# A free port on loopback, chosen at random above 32768 (below are the Supabase
# CLI and the dev servers). Known before the stack starts: the HTTPS one is
# part of DJANGO_CSRF_TRUSTED_ORIGINS. Only "connection refused" means free.
taken=""
free_port() {
    while :; do
        port=$((32768 + $(od -An -N2 -tu2 /dev/urandom | tr -d ' \n') % 28000))
        case " $taken " in *" $port "*) continue ;; esac
        rc=0
        curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$port/" || rc=$?
        [ "$rc" -eq 7 ] || continue
        taken="$taken $port"
        return 0
    done
}

HOST=smoke.test
# SMOKE_* fix a port; without them three free ones are chosen.
free_port && PLAIN=${SMOKE_HTTP_PORT:-$port}        # plain HTTP, as a reverse proxy would reach it
free_port && HTTP_TLS=${SMOKE_HTTP_TLS_PORT:-$port} # port 80 of the TLS front
free_port && HTTPS=${SMOKE_HTTPS_PORT:-$port}       # port 443 of the TLS front
export SMOKE_HTTP_TLS_PORT="$HTTP_TLS" SMOKE_HTTPS_PORT="$HTTPS"

WORK=$(mktemp -d)
ENV_FILE="$WORK/env"
JAR="$WORK/cookies"
PASSWORD="smoke-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
export ENV_FILE

cat >"$ENV_FILE" <<ENV
PARTITARIO_IMAGE=$INSTANCE-smoke
PARTITARIO_VERSION=
DJANGO_ALLOWED_HOSTS=$HOST
DJANGO_CSRF_TRUSTED_ORIGINS=https://$HOST:$HTTPS
DJANGO_SECRET_KEY=smoke-only-$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
HTTP_PORT=$PLAIN
COMPOSE_PROFILES=db
DB_HOST=db
DB_PORT=5432
DB_NAME=partitario
DB_USER=partitario_app
DB_PASSWORD=smoke-db-password
DB_SCHEMA=partitario
DB_SSLMODE=disable
DJANGO_STORAGE_BACKEND=filesystem
TURNSTILE_SITE_KEY=smoke-site-key
TURNSTILE_SECRET_KEY=smoke-secret-key
ENV

compose() {
    docker compose --progress quiet -p "$INSTANCE-smoke" --env-file "$ENV_FILE" \
        -f docker/compose.selfhost.yaml -f docker/compose.selfhost.build.yaml \
        -f tests/smoke/compose.yaml "$@"
}

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "--- container logs ---"
        compose logs --tail 40 2>/dev/null || true
    fi
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK"
    exit "$status"
}
trap cleanup EXIT INT TERM

failures=0
check() { # check <description> <expected> <actual>
    if [ "$2" = "$3" ]; then
        echo "  ok    $1"
    else
        echo "  FAIL  $1 (expected '$2', got '$3')"
        failures=$((failures + 1))
    fi
}
contains() { # contains <description> <needle> <haystack>
    case "$3" in
        *"$2"*) echo "  ok    $1" ;;
        *) echo "  FAIL  $1 (missing '$2')"; failures=$((failures + 1)) ;;
    esac
}

# curl against the plain port, the way the machine's reverse proxy would.
plain() { curl -s -H "Host: $HOST" "$@"; }
# curl against the TLS front (self-signed certificate, hence -k).
tls() { curl -sk --resolve "$HOST:$HTTPS:127.0.0.1" "$@"; }
code='%{http_code}'

echo "Building and starting the stack..."
compose up --build --detach --wait --quiet-pull >/dev/null

echo "Image"
leftovers=$(compose run --rm --no-deps -T web sh -c \
    'find . -path ./.venv -prune -o \( -type d -name tests -o -name conftest.py -o -name tailwind -o -name package.json -o -name uv.lock \
        -o -name __pycache__ -o -name "*.pyc" -o -name media -o -name .python-version -o -name "*.log" \) -print')
check "no tests, build sources or host files (bytecode, uploads) in the runtime image" "" "$leftovers"
check "web runs unprivileged, with the fixed uid" "10001" "$(compose exec -T web id -u)"
contains "web healthcheck is the readiness probe (database included)" "/readyz" \
    "$(docker inspect --format '{{json .Config.Healthcheck.Test}}' "$(compose ps -q web)")"
check "nginx runs unprivileged" "101" "$(compose exec -T nginx id -u)"
check "the task worker runs, unprivileged" "10001" "$(compose exec -T worker id -u)"
check "nginx configuration is valid" "0" "$(compose exec -T nginx nginx -t >/dev/null 2>&1; echo $?)"

echo "Backing services"
services=$(compose run --rm -T web python manage.py check_services 2>&1)
contains "database, RLS, cache and document storage" "Backing services OK." "$services"
contains "the cache is shared (a database table by default)" "DatabaseCache set/get/delete OK" "$services"

echo "Plain HTTP port (behind a reverse proxy)"
check "request that was not HTTPS is redirected" "301" \
    "$(plain -o /dev/null -w "$code" "http://127.0.0.1:$PLAIN/accounts/login/")"
check "forwarded HTTPS request is served" "200" \
    "$(plain -H 'X-Forwarded-Proto: https' -o /dev/null -w "$code" "http://127.0.0.1:$PLAIN/accounts/login/")"
check "unknown host is dropped" "000" \
    "$(curl -s -H 'Host: evil.test' -o /dev/null -w "$code" "http://127.0.0.1:$PLAIN/" || true)"
check "health endpoints are not exposed" "404" \
    "$(plain -H 'X-Forwarded-Proto: https' -o /dev/null -w "$code" "http://127.0.0.1:$PLAIN/healthz")"

echo "TLS front (staging / production)"
check "HTTP redirects to HTTPS" "301" \
    "$(curl -s -H "Host: $HOST" -o /dev/null -w "$code" "http://127.0.0.1:$HTTP_TLS/admin/")"
check "unknown host on HTTP is dropped" "000" \
    "$(curl -s -H 'Host: evil.test' -o /dev/null -w "$code" "http://127.0.0.1:$HTTP_TLS/" || true)"
check "unknown SNI is rejected" "000" \
    "$(curl -sk --resolve "evil.test:$HTTPS:127.0.0.1" -o /dev/null -w "$code" "https://evil.test:$HTTPS/" || true)"
check "TLS 1.1 is refused" "000" \
    "$(tls --tls-max 1.1 -o /dev/null -w "$code" "https://$HOST:$HTTPS/" || true)"

headers=$(tls -D - -o "$WORK/login.html" -c "$JAR" "https://$HOST:$HTTPS/accounts/login/" | tr '[:upper:]' '[:lower:]')
contains "login page over HTTPS" "http/2 200" "$headers"
contains "HSTS" "strict-transport-security: max-age=" "$headers"
contains "clickjacking protection" "x-frame-options: deny" "$headers"
contains "no content sniffing" "x-content-type-options: nosniff" "$headers"
contains "CSP (enforced)" "content-security-policy: default-src 'self'" "$headers"
contains "__Host- CSRF cookie" "set-cookie: __host-csrftoken=" "$headers"
check "server version is hidden" "server: nginx" "$(echo "$headers" | grep '^server:' | tr -d '\r')"

css=$(grep -o '/static/css/app\.[a-z0-9]*\.css' "$WORK/login.html" | head -1)
contains "static files have hashed names" "/static/css/app." "$css"
contains "static files are cached for a year" "max-age=31536000, immutable" \
    "$(tls -D - -o /dev/null "https://$HOST:$HTTPS$css" | tr '[:upper:]' '[:lower:]')"
contains "the login page has the admin's look" "unfold/css/styles." "$(cat "$WORK/login.html")"
contains "the admin has no login of its own: it redirects to the one login page" \
    "location: /accounts/login/" \
    "$(tls -D - -o /dev/null "https://$HOST:$HTTPS/admin/login/" | tr '[:upper:]' '[:lower:]')"

echo "Signup"
signup=$(tls -D "$WORK/signup.headers" "https://$HOST:$HTTPS/accounts/signup/")
contains "the signup form carries the Turnstile widget" 'class="cf-turnstile" data-sitekey="smoke-site-key"' "$signup"
contains "the CSP lets Cloudflare's Turnstile frame in, and nothing else" \
    "frame-src https://challenges.cloudflare.com;" \
    "$(tr '[:upper:]' '[:lower:]' <"$WORK/signup.headers")"
check "signup without a Turnstile token creates nobody" "0" "$(
    tls -o /dev/null -b "$JAR" -e "https://$HOST:$HTTPS/accounts/signup/" \
        -d "csrfmiddlewaretoken=$(awk '$6 == "__Host-csrftoken" {print $7}' "$JAR")" \
        -d email=bot@example.com -d password1=smoke-passphrase-1 -d password2=smoke-passphrase-1 \
        "https://$HOST:$HTTPS/accounts/signup/"
    compose exec -T web python manage.py shell -c \
        "from django.contrib.auth import get_user_model; print(get_user_model().objects.count())" | tail -1)"
contains "production refuses to start on Cloudflare's test keys" "accounts.E001" \
    "$(compose run --rm -T -e TURNSTILE_SITE_KEY= -e TURNSTILE_SECRET_KEY= web python manage.py check 2>&1 || true)"

echo "Error pages and maintenance mode"
check "unknown page answers 404" "404" \
    "$(tls -o "$WORK/404.html" -w "$code" "https://$HOST:$HTTPS/no-such-page/")"
contains "404 is the project's own page, translated" "Pagina non trovata" "$(cat "$WORK/404.html")"
compose exec -T web python manage.py maintenance_mode on >/dev/null
check "maintenance mode: visitors get 503" "503" \
    "$(tls -o "$WORK/503.html" -w "$code" "https://$HOST:$HTTPS/")"
contains "maintenance page is the project's own" "Torniamo presto" "$(cat "$WORK/503.html")"
check "maintenance mode: the login page stays reachable" "200" \
    "$(tls -o /dev/null -w "$code" "https://$HOST:$HTTPS/accounts/login/")"
compose exec -T web python manage.py maintenance_mode off >/dev/null
check "maintenance mode off: back to normal" "302" \
    "$(tls -o /dev/null -w "$code" "https://$HOST:$HTTPS/")"

echo "Login and private documents"
compose run --rm -T -e DJANGO_SUPERUSER_PASSWORD="$PASSWORD" web \
    python manage.py createsuperuser --noinput --email smoke@example.com >/dev/null
compose exec -T web sh -c 'mkdir -p /data/media/reports && printf private-document > /data/media/reports/doc.txt'
doc="https://$HOST:$HTTPS/media/reports/doc.txt"
check "anonymous request for a document goes to login" "302" "$(tls -o /dev/null -w "$code" "$doc")"
check "internal nginx location is not reachable" "404" \
    "$(tls -o /dev/null -w "$code" "https://$HOST:$HTTPS/_protected_media/reports/doc.txt")"

token=$(awk '$6 == "__Host-csrftoken" {print $7}' "$JAR")
check "password reset is accepted" "302" "$(tls -o /dev/null -w "$code" -b "$JAR" \
    -e "https://$HOST:$HTTPS/accounts/password/reset/" -d "csrfmiddlewaretoken=$token" \
    -d email=smoke@example.com "https://$HOST:$HTTPS/accounts/password/reset/")"
# No mail server here: the console backend prints the mail in the log of
# whoever sends it - the worker, not the request.
tries=0
until compose logs worker 2>/dev/null | grep -q "To: smoke@example.com"; do
    tries=$((tries + 1))
    [ "$tries" -lt 20 ] || break
    sleep 1
done
contains "the mail is sent by the worker" "To: smoke@example.com" "$(compose logs worker 2>/dev/null)"
check "and not by the request" "0" "$(compose logs web 2>/dev/null | grep -c "To: smoke@example.com")"
# The address is typed with capitals: addresses are lowercase, login does not care.
check "login succeeds" "302" "$(tls -o /dev/null -w "$code" -b "$JAR" -c "$JAR" \
    -e "https://$HOST:$HTTPS/accounts/login/" -d "csrfmiddlewaretoken=$token" \
    -d login=SMOKE@example.com --data-urlencode "password=$PASSWORD" -d next=/admin/ \
    "https://$HOST:$HTTPS/accounts/login/")"
contains "staff without a second factor are sent to set it up" "location: /accounts/2fa/" \
    "$(tls -D - -o /dev/null -b "$JAR" "https://$HOST:$HTTPS/admin/" | tr '[:upper:]' '[:lower:]')"
# What the setup page does once the user scans the QR code and types a code.
compose exec -T web python manage.py shell -c "
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.contrib.auth import get_user_model
TOTP.activate(get_user_model().objects.get(email='smoke@example.com'), generate_totp_secret())" >/dev/null
check "admin index once two-factor authentication is set up" "200" \
    "$(tls -o "$WORK/admin.html" -w "$code" -b "$JAR" "https://$HOST:$HTTPS/admin/")"
# English source string, Italian from locale/it compiled into the image.
contains "translations are compiled into the image" "Pannello di amministrazione" "$(cat "$WORK/admin.html")"
body=$(tls -D "$WORK/doc.headers" -b "$JAR" "$doc")
check "logged-in user gets the document through nginx" "private-document" "$body"
contains "documents are served sandboxed" "content-security-policy: sandbox" \
    "$(tr '[:upper:]' '[:lower:]' <"$WORK/doc.headers")"

echo "Login rate limit"
codes=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    codes="$codes $(tls -o /dev/null -w "$code" -e "https://$HOST:$HTTPS/accounts/login/" \
        -d login=x -d password=y "https://$HOST:$HTTPS/accounts/login/")"
done
contains "repeated login POSTs are throttled" "429" "$codes"

echo
if [ "$failures" -ne 0 ]; then
    echo "Smoke test FAILED: $failures check(s)."
    exit 1
fi
echo "Smoke test passed."
