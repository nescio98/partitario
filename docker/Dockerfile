# Base images are pinned to a release line; bump them deliberately.
ARG NODE_IMAGE=node:24-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:python3.13-trixie-slim
ARG PYTHON_IMAGE=python:3.13-slim-trixie
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.30-alpine

## ------------------------------ CSS builder -------------------------------- ##
# The stylesheet is the same on every architecture: build it natively, even
# when the image itself is cross-built (linux/arm64 under emulation).
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS css-builder
WORKDIR /css
COPY package.json package-lock.json ./
RUN npm ci
# Build context is ../django. Tailwind scans templates and Python files for class names.
COPY . .
RUN npm run build:css

## ------------------------------ Python builder ----------------------------- ##
FROM ${UV_IMAGE} AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
ENV APP_HOME=/home/app/web
WORKDIR $APP_HOME

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
# Only what runs in production: no tests, no Tailwind sources, no lock files.
COPY manage.py gunicorn.conf.py ./
COPY config ./config
COPY apps ./apps
COPY templates ./templates
COPY static ./static
COPY locale ./locale
RUN find apps -type d -name tests -prune -exec rm -rf {} +
# Translations: compile locale/*/LC_MESSAGES/django.po into the .mo files Django
# reads (they are not committed). gettext stays in this stage.
RUN apt-get update && apt-get install -y --no-install-recommends gettext \
    && rm -rf /var/lib/apt/lists/*
# No .pyc for the application code: the image carries none from the host
# (Dockerfile.dockerignore) and writes none of its own.
RUN DJANGO_BUILD=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python manage.py compilemessages --ignore .venv

## ------------------------------ Application -------------------------------- ##
FROM ${PYTHON_IMAGE} AS app

# Fixed uid/gid, so the owner of the `media` volume (and of anything bind
# mounted) is the same on every machine and in every release.
RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app app
ENV APP_HOME=/home/app/web
WORKDIR $APP_HOME

COPY --from=builder --chown=app:app $APP_HOME $APP_HOME
COPY --from=css-builder --chown=app:app /css/static/css/app.css $APP_HOME/static/css/app.css
# /data/media: uploaded documents when DJANGO_STORAGE_BACKEND=filesystem (a volume).
RUN mkdir -p $APP_HOME/staticfiles /data/media && chown app:app $APP_HOME/staticfiles /data/media

# No .pyc writes at runtime: the hosted stacks mount the filesystem read-only.
ENV PATH="$APP_HOME/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_MEDIA_ROOT=/data/media
USER 10001:10001

# DJANGO_BUILD=1 lets settings load without runtime configuration. DEBUG is
# off, so the output has hashed file names (ManifestStaticFilesStorage).
RUN DJANGO_BUILD=1 python manage.py collectstatic --noinput --clear

EXPOSE 8000
# Workers, threads and timeouts: gunicorn.conf.py.
CMD ["gunicorn", "config.wsgi:application"]

## ------------------------------ nginx --------------------------------------- ##
# nginx of the hosted stacks: static files, reverse proxy to gunicorn and, with
# NGINX_TLS=on (staging / production), TLS. Runs as an unprivileged user
# (uid 101). Its configuration is baked in, so the image runs without the
# repository; it comes from the `docker` build context (the docker/ folder).
FROM ${NGINX_IMAGE} AS nginx
USER 0
# openssl: placeholder self-signed certificate until Let's Encrypt has issued one.
RUN apk add --no-cache openssl
# Plain HTTP application server (always) ...
COPY --from=docker nginx/default.conf.template /etc/nginx/templates/
# ... and the same plus the TLS front, selected by 12-tls-mode.envsh.
COPY --from=docker nginx/default.conf.template nginx/tls.conf.template /etc/nginx/templates-tls/
COPY --from=docker --chmod=755 nginx/12-tls-mode.envsh nginx/40-tls-certificates.sh /docker-entrypoint.d/
# The image's unprivileged `nginx` user.
USER 101
COPY --from=app /home/app/web/staticfiles /usr/share/nginx/html/static

## ------------------------------ Runtime (default target) ------------------- ##
FROM app AS production
