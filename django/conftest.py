"""Shared pytest fixtures for every app.

Tests run against a throwaway `test_*` database, created and migrated by
pytest-django on whatever PostgreSQL `DB_*` points at: a disposable container
(`make test`, tests/pytest/test-postgres.sh) or the local Supabase stack (`make test-supabase`).
"""

import pytest


@pytest.fixture(autouse=True)
def _test_storages(settings):
    """Never let a test upload to the real bucket: swap it for memory storage.

    Static files use the plain storage: there is no collectstatic manifest.
    """
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _staff_mfa_optional(settings):
    """Staff can use the admin without a second factor, whatever DJANGO_DEBUG
    says in the environment; the tests of the requirement switch it back on."""
    settings.STAFF_MFA_REQUIRED = False


@pytest.fixture(autouse=True)
def _tasks_run_at_once(settings):
    """No worker in tests: a task runs inside the call that enqueues it."""
    settings.TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}


@pytest.fixture(autouse=True)
def _no_captcha(settings):
    """The signup form has no Turnstile field: validating one asks Cloudflare.
    The tests of the field switch it back on and replace the call."""
    settings.TURNSTILE_ENABLED = False


@pytest.fixture
def create_user(django_user_model):
    """create_user(email, **fields): a user who can log in at once - with a
    password and, unless `verified=False`, a confirmed address."""
    from allauth.account.models import EmailAddress

    def create(email, password="a-long-passphrase-1", verified=True, **fields):
        user = django_user_model.objects.create_user(email, password, **fields)
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=verified)
        return user

    return create
