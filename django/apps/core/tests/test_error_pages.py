"""The project's own error pages, self-contained (no static files, no database)."""

import pytest
from django.test import RequestFactory
from django.views import defaults


def test_404_uses_the_project_page(client, db):
    response = client.get("/this-page-does-not-exist/")
    assert response.status_code == 404
    assert "errors/base.html" in [t.name for t in response.templates]
    assert 'class="code">404<' in response.content.decode()


@pytest.mark.parametrize(
    ("view", "status"),
    [
        (lambda r: defaults.bad_request(r, Exception()), 400),
        (lambda r: defaults.permission_denied(r, Exception()), 403),
        (lambda r: defaults.server_error(r), 500),
    ],
)
def test_other_error_pages_render_without_a_database(view, status):
    # No `db` fixture: rendering must not touch the database.
    response = view(RequestFactory().get("/"))
    assert response.status_code == status
    body = response.content.decode()
    assert f'class="code">{status}<' in body
    assert "/static/" not in body
