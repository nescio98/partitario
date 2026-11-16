import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.fixture
def superuser_env(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "Simone@Example.com")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "a-long-passphrase-1")


@pytest.mark.django_db
def test_creates_the_superuser_once(superuser_env, django_user_model, monkeypatch):
    call_command("ensure_superuser")
    user = django_user_model.objects.get(email="simone@example.com")
    assert user.is_superuser
    assert user.check_password("a-long-passphrase-1")

    # A second run never touches the existing user, whatever the env says.
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "another-passphrase-2")
    call_command("ensure_superuser")
    user.refresh_from_db()
    assert user.check_password("a-long-passphrase-1")


@pytest.mark.django_db
def test_requires_email_and_password(monkeypatch):
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "simone@example.com")
    with pytest.raises(CommandError):
        call_command("ensure_superuser")
