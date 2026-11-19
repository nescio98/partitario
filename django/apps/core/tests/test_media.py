"""Uploaded documents on disk (STORAGE_BACKEND=filesystem) are never public."""

import pytest


@pytest.fixture
def document(settings, tmp_path):
    settings.STORAGE_BACKEND = "filesystem"
    settings.MEDIA_ROOT = tmp_path
    # The view resolves paths through the storage: use the real one, not the
    # in-memory storage of conftest.
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    }
    settings.MEDIA_ACCEL_REDIRECT = False
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "annual.pdf").write_bytes(b"%PDF-report")
    return "/media/reports/annual.pdf"


@pytest.mark.django_db
def test_anonymous_user_is_sent_to_login(client, document):
    response = client.get(document)
    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_logged_in_user_gets_the_file(admin_client, document):
    response = admin_client.get(document)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-report"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_behind_nginx_the_transfer_is_handed_over(admin_client, document, settings):
    settings.MEDIA_ACCEL_REDIRECT = True
    response = admin_client.get(document)
    assert response.status_code == 200
    assert response["X-Accel-Redirect"] == "/_protected_media/reports/annual.pdf"
    assert response.content == b""


@pytest.mark.parametrize("path", ["/media/missing.pdf", "/media/../manage.py", "/media/reports/"])
def test_missing_or_escaping_paths_are_not_found(admin_client, document, path):
    assert admin_client.get(path).status_code == 404


def test_view_is_disabled_with_s3_storage(admin_client, document, settings):
    settings.STORAGE_BACKEND = "s3"
    assert admin_client.get(document).status_code == 404
