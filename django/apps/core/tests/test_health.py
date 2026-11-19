import pytest


def test_healthz_ignores_allowed_hosts_and_https_redirect(client, settings):
    settings.ALLOWED_HOSTS = ["ledger.example.com"]
    settings.SECURE_SSL_REDIRECT = True
    response = client.get("/healthz", headers={"host": "127.0.0.1:8000"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_readyz_checks_the_database(client):
    assert client.get("/readyz").status_code == 200
