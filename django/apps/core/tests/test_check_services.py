import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core import diagnostics


@pytest.fixture
def s3_bucket(settings, monkeypatch):
    """An S3 configuration whose bucket lives in memory (see conftest)."""
    settings.STORAGE_BACKEND = "s3"
    settings.S3_BUCKET = "documents"
    monkeypatch.setattr(
        diagnostics, "unsigned_urls", lambda name: [f"https://s3.test/documents/{name}"]
    )


@pytest.mark.django_db
def test_private_bucket_passes(s3_bucket, monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "is_publicly_readable", lambda url: False)
    call_command("check_services")
    assert "bucket=documents private" in capsys.readouterr().out


@pytest.mark.django_db
def test_public_bucket_fails(s3_bucket, monkeypatch):
    monkeypatch.setattr(diagnostics, "is_publicly_readable", lambda url: True)
    with pytest.raises(CommandError, match="PUBLIC"):
        call_command("check_services")


@pytest.mark.django_db
def test_filesystem_storage_passes(settings, tmp_path, capsys):
    settings.STORAGE_BACKEND = "filesystem"
    settings.MEDIA_ROOT = tmp_path
    call_command("check_services")
    assert "write/read/delete OK" in capsys.readouterr().out


@pytest.mark.django_db
def test_table_without_rls_fails(s3_bucket, monkeypatch):
    monkeypatch.setattr(diagnostics, "is_publicly_readable", lambda url: False)
    monkeypatch.setattr(diagnostics, "tables_without_rls", lambda: ["blog_post"])
    with pytest.raises(CommandError, match="blog_post"):
        call_command("check_services")


def test_unreachable_url_is_not_readable():
    # Nothing listens on this port: a refused connection is "not public", not a crash.
    assert diagnostics.is_publicly_readable("http://127.0.0.1:9/documents/x") is False


def test_only_http_urls_are_probed():
    with pytest.raises(ValueError, match="not an HTTP"):
        diagnostics.is_publicly_readable("file:///etc/passwd")


@pytest.mark.django_db
def test_each_check_runs_on_its_own():
    assert diagnostics.check_database().problems == []
    assert diagnostics.check_rls().problems == []
