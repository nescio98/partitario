"""Checks of the backing services, behind `manage.py check_services`.

Each check is a plain function returning what it found, so it can be run and
tested on its own. They work on any PostgreSQL, any S3-compatible store or a
local directory; one extra URL is probed when the store is Supabase.
"""

import urllib.request
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection

from .schema import tables_without_rls

# Supabase Storage exposes its S3 protocol under this path, next to a public
# object API that an S3 client never sees.
SUPABASE_S3_SUFFIX = "/storage/v1/s3"

PROBE_CONTENT = b"partitario"
PROBE_TIMEOUT = 10  # seconds


@dataclass(frozen=True)
class CheckResult:
    """One line for the operator, plus the problems found (none = passed)."""

    summary: str
    problems: list[str] = field(default_factory=list)


def check_database() -> CheckResult:
    """The connection works and resolves tables to the Django schema."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, current_schema(), version()")
        user, schema, version = cursor.fetchone()
    problems = []
    if schema != settings.DB_SCHEMA:
        problems.append(
            f"current schema is {schema!r}, expected {settings.DB_SCHEMA!r} "
            "(run migrate; avoid a transaction-mode pooler)"
        )
    return CheckResult(f"DB       user={user} schema={schema} ({version.split(',')[0]})", problems)


def check_rls() -> CheckResult:
    """Every table of the Django schema has Row Level Security enabled."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname = %s", [settings.DB_SCHEMA])
        table_count = cursor.fetchone()[0]
    unprotected = tables_without_rls()
    problems = []
    if table_count == 0:
        problems.append("no tables found — run `manage.py migrate`")
    if unprotected:
        problems.append(f"tables without RLS: {', '.join(unprotected)}")
    return CheckResult(
        f"RLS      {table_count - len(unprotected)}/{table_count} tables protected", problems
    )


def check_cache() -> CheckResult:
    """The shared cache accepts a value and gives it back."""
    backend = str(settings.CACHES["default"]["BACKEND"]).rsplit(".", 1)[-1]
    key = f"_healthcheck:{uuid.uuid4().hex}"
    try:
        cache.set(key, "ok", timeout=30)
        value = cache.get(key)
        cache.delete(key)
    except Exception as exc:  # whatever the backend raises is the finding
        return CheckResult(
            f"Cache    {backend} NOT working",
            [f"cache ({backend}) failed: {exc} (run migrate; is DJANGO_CACHE_URL right?)"],
        )
    if value != "ok":
        return CheckResult(f"Cache    {backend} FAILED", ["cache round trip lost the value"])
    return CheckResult(f"Cache    {backend} set/get/delete OK")


def check_storage() -> CheckResult:
    """A document can be written, read back and deleted, and is not public."""
    label = _storage_label()
    name = f"_healthcheck/{uuid.uuid4().hex}.txt"
    try:
        saved = default_storage.save(name, ContentFile(PROBE_CONTENT))
    except Exception as exc:  # whatever the backend raises is the finding
        return CheckResult(
            f"Storage  {label} NOT writable",
            [
                f"cannot write to storage ({label}): {exc} "
                "(does it exist? are the S3_* / DJANGO_MEDIA_ROOT settings right?)"
            ],
        )

    problems = []
    try:
        with default_storage.open(saved) as fh:
            if fh.read() != PROBE_CONTENT:
                problems.append("storage round trip returned different content")
        # Seen from the outside, the way a browser would: requests without a
        # signature must be refused. A directory has no public URL at all:
        # files only leave through the login-protected view (apps/core/views.py).
        if any(is_publicly_readable(url) for url in unsigned_urls(saved)):
            problems.append(f"storage ({label}) is PUBLIC — it must be private")
    finally:
        default_storage.delete(saved)

    outcome = "FAILED" if problems else "private, write/read/delete OK"
    return CheckResult(f"Storage  {label} {outcome}", problems)


def unsigned_urls(name: str) -> list[str]:
    """URLs at which a stored object would be readable if the store were public."""
    if settings.STORAGE_BACKEND != "s3":
        return []
    # Any S3 store: the object URL with its signature stripped.
    urls = [default_storage.url(name).split("?", 1)[0]]
    # Supabase serves public buckets from a separate, non-S3 endpoint.
    endpoint = (getattr(default_storage, "endpoint_url", None) or "").rstrip("/")
    if endpoint.endswith(SUPABASE_S3_SUFFIX):
        base = endpoint.removesuffix(SUPABASE_S3_SUFFIX)
        urls.append(f"{base}/storage/v1/object/public/{settings.S3_BUCKET}/{name}")
    return urls


def is_publicly_readable(url: str) -> bool:
    """True when an anonymous GET of the URL succeeds.

    A refusal, a timeout or an unreachable host all mean "not readable".
    """
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError(f"not an HTTP(S) URL: {url!r}")
    try:
        # The scheme is restricted just above.
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:  # noqa: S310
            return bool(response.status == HTTPStatus.OK)
    except OSError:  # URLError and HTTPError included
        return False


def _storage_label() -> str:
    if settings.STORAGE_BACKEND == "filesystem":
        return f"directory={settings.MEDIA_ROOT}"
    return f"bucket={settings.S3_BUCKET}"
