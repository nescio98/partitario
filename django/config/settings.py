"""Django settings for partitario.

Every environment-specific value comes from the environment (a local `.env`
loaded by python-dotenv, or the docker compose `environment:` block), parsed by
`config.env`. There are no silent fallbacks: a missing required variable, or a
malformed one, fails startup with a clear error. See `.env.example` for the
full list.

Variable names carry the prefix of their group: `DJANGO_*` (framework and
application), `DB_*`, `S3_*`, `EMAIL_*`, `TURNSTILE_*`. `ENV` names the environment.
"""

from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.csp import CSP
from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv

from config.env import env_bool, env_int, env_list, env_str

# BASE_DIR is the Django project (`django/`); the repository root is one level up
# and holds the single `.env` shared with docker compose.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

load_dotenv(REPO_DIR / ".env")


# --- Core -------------------------------------------------------------------

# dev | local | staging | prod | selfhost — set by .env or by the compose file.
# Informational: no setting branches on it, security derives from DEBUG alone.
# One check reads it: production must not run on Turnstile's test keys
# (apps/accounts/checks.py).
ENV = env_str("ENV", "dev")

SECRET_KEY = env_str("DJANGO_SECRET_KEY")
# Old keys still accepted for sessions and signed data while rotating the key.
SECRET_KEY_FALLBACKS = env_list("DJANGO_SECRET_KEY_FALLBACKS")
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=None)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # Unfold must come before django.contrib.admin.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "unfold.contrib.hijack",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "storages",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.usersessions",
    "hijack",
    "hijack.contrib.admin",
    "maintenance_mode",
    "django_tasks_db",
    # Project apps (see docs/architecture.md for the dependency direction)
    "apps.core",
    "apps.accounts",
]

MIDDLEWARE = [
    # First: answers /healthz and /readyz before host validation and the HTTPS
    # redirect, so container healthchecks work over plain HTTP on 127.0.0.1.
    "apps.core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # After authentication: both need to know who is asking.
    "maintenance_mode.middleware.MaintenanceModeMiddleware",
    "hijack.middleware.HijackUserMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    # Last: staff without two-factor authentication are sent to set it up.
    "apps.accounts.middleware.RequireStaffMFAMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # The Unfold look for the allauth pages (templates/allauth/).
                "apps.accounts.context_processors.account_pages",
            ],
        },
    },
]

# --- Database: PostgreSQL -----------------------------------------------------
# Any PostgreSQL server. dev / staging / prod use Supabase; selfhost uses
# whatever DB_* points at.
#
# All Django tables live in a dedicated schema (default `partitario`) instead of
# `public`, and RLS is enabled on every table after each `migrate`
# (apps/core/schema.py): on Supabase that keeps them out of reach of its Data API,
# elsewhere it is harmless.
#
# Behind a connection pooler use session mode (port 5432 on hosted Supabase):
# transaction mode (6543) does not honour the search_path startup option.

DB_SCHEMA = env_str("DB_SCHEMA", "partitario")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("DB_NAME"),
        "USER": env_str("DB_USER"),
        "PASSWORD": env_str("DB_PASSWORD"),
        "HOST": env_str("DB_HOST"),
        "PORT": env_str("DB_PORT"),
        # Seconds a connection is kept open and reused (0 = one per request).
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 0),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "options": f"-c search_path={DB_SCHEMA}",
            "sslmode": env_str("DB_SSLMODE", "prefer"),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache --------------------------------------------------------------------
# One store shared by every gunicorn worker and container. Django's default is
# a private memory cache per process, which makes anything counted in it
# (allauth's rate limits) or invalidated through it unreliable.
#
#   default              a table in the database: no extra service. It makes the
#                        cache shared and correct, not fast - do not cache a
#                        query in it to save a query.
#   DJANGO_CACHE_URL     redis://host:6379/0 - Redis or Valkey, when a project
#                        needs caching for speed (compose profile `cache`).
#
# The table is created by `migrate` (apps/core/signals.py), like the schema.
_cache_url = env_str("DJANGO_CACHE_URL", "")
CACHE_TABLE = "django_cache"
CACHES: dict[str, dict[str, object]]
if _cache_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _cache_url,
            # The server may be shared with other projects.
            "KEY_PREFIX": "partitario",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": CACHE_TABLE,
            "OPTIONS": {"MAX_ENTRIES": 10_000},
        }
    }

# --- Auth --------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Argon2 for new passwords; PBKDF2 hashes are upgraded on the next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# django-allauth: the one way in. Account pages live under /accounts/ (signup,
# login, logout, email address, password change/reset, two-factor
# authentication) and the admin login redirects there (config/urls.py), so its
# rate limits and second factor apply to everybody.
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
# People are their email address: accounts.User has no username.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# Nobody gets in before clicking the link mailed to their address - whether
# they signed up or were created in the admin.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# One address per user; a new one replaces it once confirmed (/accounts/email/).
ACCOUNT_CHANGE_EMAIL = True
# False closes signup: users are then only created in the admin.
ACCOUNT_SIGNUP_OPEN = env_bool("DJANGO_ACCOUNT_SIGNUP_OPEN", default=True)
ACCOUNT_FORMS = {"signup": "apps.accounts.forms.SignupForm"}
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "home"
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"
# No "remember me": the session ends with the browser, or after
# SESSION_COOKIE_AGE at the latest.
ACCOUNT_SESSION_REMEMBER = False
# Password reset: an address nobody registered gets no mail at all, so nobody
# can use the form to make this server write to third parties. (Signing up
# with a registered address looks like any other signup: its owner is told by
# mail, the stranger learns nothing.)
ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS = False
# "Your password was changed", "an authenticator was added", ... by mail.
ACCOUNT_EMAIL_NOTIFICATIONS = True
# Changing the password or the second factor asks for the password again.
ACCOUNT_REAUTHENTICATION_REQUIRED = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[partitario] "

# Two-factor authentication (allauth.mfa): authenticator app, security keys,
# recovery codes.
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes", "webauthn"]
MFA_TOTP_ISSUER = "partitario"
# Staff (everyone who can open the admin) must have a second factor: without
# one, every page redirects to its setup (apps/accounts/middleware.py). On by
# default outside DEBUG.
STAFF_MFA_REQUIRED = env_bool("DJANGO_STAFF_MFA_REQUIRED", default=not DEBUG)

# Bot protection of the signup form: Cloudflare Turnstile
# (apps/accounts/turnstile.py), which rarely asks the visitor anything.
# Without keys it uses Cloudflare's public test keys, which show the widget
# and accept everybody: right for dev and staging, refused at startup where
# real people sign up (apps/accounts/checks.py). TURNSTILE_ENABLED=False
# removes the field: the local stack, and the tests.
TURNSTILE_ENABLED = env_bool("TURNSTILE_ENABLED", default=True)
# Public, good on any host name; a real secret key refuses the token they produce.
TURNSTILE_TEST_KEYS = ("1x00000000000000000000AA", "1x0000000000000000000000000000000AA")
TURNSTILE_SITE_KEY = env_str("TURNSTILE_SITE_KEY", TURNSTILE_TEST_KEYS[0])
TURNSTILE_SECRET_KEY = env_str("TURNSTILE_SECRET_KEY", TURNSTILE_TEST_KEYS[1])

# Sessions (allauth.usersessions): under /accounts/sessions/ users see where
# they are logged in (since when, from which address and browser) and can end
# every other session. "Last seen" is left out on purpose: tracking it
# (USERSESSIONS_TRACK_ACTIVITY and its middleware) writes to the database on
# every request.

# allauth counts its rate limits per client address, in the cache. Behind nginx
# the connection always comes from nginx, which overwrites X-Forwarded-For with
# the one address it trusts: that single hop is believed. Under runserver
# (DEBUG) there is no proxy and the header is ignored.
ALLAUTH_TRUSTED_PROXY_COUNT = 0 if DEBUG else 1

# django-hijack: a superuser can act as another user from the admin user list
# ("impersonate"), to see what they see. Who may do it is decided by one
# function, and every start and end is logged (apps/accounts/signals.py).
HIJACK_PERMISSION_CHECK = "apps.accounts.permissions.can_hijack"

# Background tasks (django.tasks): a row in the database, run by the `worker`
# container (`manage.py db_worker`) - no broker to operate. Under DEBUG there
# is no worker to start: a task runs at once, inside the caller.
TASKS_IMMEDIATE = env_bool("DJANGO_TASKS_IMMEDIATE", default=DEBUG)
TASKS = {
    "default": {
        "BACKEND": (
            "django.tasks.backends.immediate.ImmediateBackend"
            if TASKS_IMMEDIATE
            else "django_tasks_db.DatabaseBackend"
        ),
    }
}

# Mail (password reset, security notifications) never leaves from a request:
# the default mailer queues each message as a task (apps/core/mail.py), which
# sends it through `transport` - SMTP when EMAIL_HOST is set, otherwise mails
# are only printed to the log: fine for development, but `check --deploy`
# rejects it.
_transport: dict[str, object]
_email_host = env_str("EMAIL_HOST", "")
if _email_host:
    _email_use_ssl = env_bool("EMAIL_USE_SSL", default=False)
    _transport = {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": _email_host,
            # 0 = the default port of the encryption: 587 (STARTTLS) or 465 (SSL).
            "port": env_int("EMAIL_PORT", 0) or None,
            "username": env_str("EMAIL_HOST_USER", ""),
            "password": env_str("EMAIL_HOST_PASSWORD", ""),
            "use_ssl": _email_use_ssl,
            "use_tls": not _email_use_ssl and env_bool("EMAIL_USE_TLS", default=True),
            "timeout": 10,
        },
    }
else:
    _transport = {"BACKEND": "apps.core.mail.ConsoleEmailBackend"}
MAILERS = {
    "default": {"BACKEND": "apps.core.mail.QueuedEmailBackend"},
    "transport": _transport,
}
DEFAULT_FROM_EMAIL = env_str("EMAIL_DEFAULT_FROM", "partitario@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --- I18N: Italian UI by default, Italian number/date formats ----------------

LANGUAGE_CODE = "it"
LANGUAGES = [("it", _("Italian")), ("en", _("English"))]
# Source strings are English; translations live in locale/<lang>/LC_MESSAGES/
# (`make messages` to extract, `make compilemessages` to compile).
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

# --- Static files & storage ---------------------------------------------------
# Static: local filesystem. `static/css/app.css` is compiled by Tailwind from
# `tailwind/app.css`: by the image build, and by the watcher of `make worktree-up`.
# Outside DEBUG Django does not serve /static/: nginx serves the output of
# collectstatic (docker/nginx/), whose file names carry a content hash
# (config/storage.py, a ManifestStaticFilesStorage) so they can be cached forever.
# Media (uploaded documents): see STORAGE_BACKEND below — Supabase
# Storage for dev / staging / prod; any S3 service or a local directory for
# selfhost.

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded documents are private wherever they live:
#   s3          a private bucket; every URL handed out is a signed, short-lived one
#   filesystem  a directory (a Docker volume when self-hosting); files are
#               served only to logged-in users, by apps/core/views.py
STORAGE_BACKEND = env_str("DJANGO_STORAGE_BACKEND", "s3")
if STORAGE_BACKEND not in {"s3", "filesystem"}:
    raise ImproperlyConfigured(
        f"DJANGO_STORAGE_BACKEND must be 's3' or 'filesystem', not {STORAGE_BACKEND!r}"
    )

MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env_str("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))
# Behind nginx the file transfer is handed over to it (X-Accel-Redirect);
# without nginx (runserver) Django streams the file itself.
MEDIA_ACCEL_REDIRECT = env_bool("DJANGO_MEDIA_ACCEL_REDIRECT", default=not DEBUG)

# Always defined, empty when the documents are not in a bucket.
S3_BUCKET = env_str("S3_BUCKET") if STORAGE_BACKEND == "s3" else ""

# Where the browser fetches a document from: this site (filesystem), or the
# origin of the signed URLs (s3). The Content Security Policy below allows
# images and media from it, so a picture or a PDF preview can be shown inline.
_document_origins: list[str] = []
_default_storage: dict[str, object]
if STORAGE_BACKEND == "s3":
    _s3_endpoint = urlsplit(
        env_str("S3_ENDPOINT_URL", "") or f"https://s3.{env_str('S3_REGION')}.amazonaws.com"
    )
    _s3_host = _s3_endpoint.netloc
    if env_str("S3_ADDRESSING_STYLE", "path") == "virtual":
        _s3_host = f"{S3_BUCKET}.{_s3_host}"
    _document_origins = [f"{_s3_endpoint.scheme}://{_s3_host}"]
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": S3_BUCKET,
            # Empty for AWS S3 itself, which derives the endpoint from the region.
            "endpoint_url": env_str("S3_ENDPOINT_URL", "") or None,
            "region_name": env_str("S3_REGION"),
            "access_key": env_str("S3_ACCESS_KEY_ID"),
            "secret_key": env_str("S3_SECRET_ACCESS_KEY"),
            # path:    https://endpoint/bucket/key  (Supabase, MinIO, most others)
            # virtual: https://bucket.endpoint/key  (AWS S3, R2)
            "addressing_style": env_str("S3_ADDRESSING_STYLE", "path"),
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 300,
            "file_overwrite": False,
        },
    }
else:
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "config.storage.LenientManifestStaticFilesStorage"
        ),
    },
}

# --- Maintenance mode ---------------------------------------------------------
# django-maintenance-mode: switched from the admin ("Maintenance mode") or with
# `manage.py maintenance_mode on|off`. Visitors get templates/503.html with
# HTTP 503; staff, superusers and the admin site keep working. The state lives
# in the database (apps/core/maintenance.py), shared by every worker.
MAINTENANCE_MODE_STATE_BACKEND = "apps.core.maintenance.DatabaseStateBackend"
MAINTENANCE_MODE_IGNORE_ADMIN_SITE = True
MAINTENANCE_MODE_IGNORE_STAFF = True
MAINTENANCE_MODE_IGNORE_SUPERUSER = True
# The login pages stay reachable, or nobody could log in to switch it off.
MAINTENANCE_MODE_IGNORE_URLS = (r"^/accounts/",)
MAINTENANCE_MODE_TEMPLATE = "503.html"
MAINTENANCE_MODE_RETRY_AFTER = 600  # seconds, sent as the Retry-After header

# --- Security ----------------------------------------------------------------
# Secure by default: with DEBUG off the app expects to sit behind nginx and a
# TLS terminating reverse proxy (docker/compose.*.yaml). Each flag can still be
# overridden from the environment (DJANGO_<setting name>).

_secure = not DEBUG

# Deliberate: HSTS for subdomains and browser preload are opt-in (see below),
# because they commit the whole domain, not just this site.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=_secure)
if env_bool("DJANGO_SECURE_PROXY_SSL_HEADER", default=_secure):
    # Set by nginx from what the reverse proxy reports, never passed on as received.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Start low; raise to 31536000 once HTTPS is confirmed to work on the domain.
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 3600 if _secure else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)

SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", default=_secure)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", default=_secure)
if SESSION_COOKIE_SECURE:
    # __Host-: the browser only accepts the cookie over HTTPS, for this exact host.
    SESSION_COOKIE_NAME = "__Host-sessionid"
if CSRF_COOKIE_SECURE:
    CSRF_COOKIE_NAME = "__Host-csrftoken"
# Development only: browsers do not separate cookies by port, so two dev
# servers on localhost (one per worktree, `make env` gives each its port)
# would overwrite each other's session. Nothing changes without
# DJANGO_DEV_PORT, which no hosted env file sets.
_dev_port = env_str("DJANGO_DEV_PORT", "")
if DEBUG and _dev_port:
    if not SESSION_COOKIE_SECURE:
        SESSION_COOKIE_NAME = f"sessionid_{_dev_port}"
    if not CSRF_COOKIE_SECURE:
        CSRF_COOKIE_NAME = f"csrftoken_{_dev_port}"
    LANGUAGE_COOKIE_NAME = f"django_language_{_dev_port}"
SESSION_COOKIE_AGE = env_int("DJANGO_SESSION_COOKIE_AGE", 8 * 60 * 60)

X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Content Security Policy, enforced: scripts, styles, fonts and images only
# from this site, no plugins, no framing, forms post only here. Unfold's
# Alpine.js evaluates expressions and uses inline handlers, hence 'unsafe-eval'
# and 'unsafe-inline': the policy still stops anything loaded from elsewhere.
# Two exceptions: documents in a bucket (see _document_origins above) and the
# Turnstile widget of the signup form, Cloudflare's script and frame.
# A project that adds an external source (a CDN, an embedded map, an analytics
# script) lists it here. DJANGO_CSP_REPORT_ONLY=True only reports violations in
# the browser console, to find what a new page needs without breaking it.
_turnstile = ["https://challenges.cloudflare.com"] if TURNSTILE_ENABLED else []
_csp = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.UNSAFE_INLINE, CSP.UNSAFE_EVAL, *_turnstile],
    "frame-src": _turnstile or [CSP.NONE],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", *_document_origins],
    "media-src": [CSP.SELF, *_document_origins],
    "font-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
if env_bool("DJANGO_CSP_REPORT_ONLY", default=False):
    SECURE_CSP_REPORT_ONLY = _csp
else:
    SECURE_CSP = _csp

# --- Logging ------------------------------------------------------------------
# Everything to stdout/stderr: `docker compose logs` is the log store.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": env_str("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        # Replace Django's default handlers (mail_admins, DEBUG-only console).
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Unfold admin -------------------------------------------------------------
# https://unfoldadmin.com/docs/configuration/settings/

UNFOLD = {
    "SITE_TITLE": "partitario",
    "SITE_HEADER": "partitario",
    "SITE_SUBHEADER": _("Administration panel"),
    "SITE_SYMBOL": "widgets",  # Material Symbols icon name: fonts.google.com/icons
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "BORDER_RADIUS": "8px",
    # Project utilities compiled by Tailwind on top of Unfold's own stylesheet.
    "STYLES": [lambda request: static("css/app.css")],
    # Extra entries of the user menu (top right).
    "ACCOUNT": {
        "navigation": [
            {
                "title": _("Account"),
                "link": reverse_lazy("account_manage"),
            },
        ],
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Administration"),
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:accounts_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                    {
                        "title": _("Background tasks"),
                        "icon": "schedule",
                        "link": reverse_lazy("admin:django_tasks_database_dbtaskresult_changelist"),
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": _("Maintenance mode"),
                        "icon": "construction",
                        "link": reverse_lazy("admin:core_maintenancemode_changelist"),
                    },
                ],
            },
        ],
    },
}
