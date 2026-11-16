"""Maintenance mode: visitors get the 503 page, staff and the admin keep working."""

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.core.maintenance import DatabaseStateBackend
from apps.core.models import MaintenanceMode


@pytest.fixture
def maintenance_on(db):
    DatabaseStateBackend().set_value(True)


@pytest.mark.django_db
def test_off_by_default(client):
    assert DatabaseStateBackend().get_value() is False
    assert client.get(reverse("account_login")).status_code == 200


def test_visitors_get_the_maintenance_page(client, maintenance_on):
    response = client.get("/")
    assert response.status_code == 503
    assert response["Retry-After"] == "600"
    assert "503" in response.content.decode()


def test_staff_and_the_admin_site_keep_working(client, admin_client, maintenance_on):
    assert admin_client.get(reverse("admin:index")).status_code == 200
    # The login pages stay reachable, or nobody could log in to switch it off.
    assert client.get(reverse("account_login")).status_code == 200
    response = client.get(reverse("admin:login"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_login"))


def test_health_checks_are_not_affected(client, maintenance_on):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


@pytest.mark.django_db
def test_the_management_command_switches_it(client):
    call_command("maintenance_mode", "on")
    assert MaintenanceMode.load().enabled is True
    call_command("maintenance_mode", "off")
    assert MaintenanceMode.load().enabled is False


def test_the_admin_has_one_row_that_cannot_be_added_or_deleted(admin_client):
    response = admin_client.get(reverse("admin:core_maintenancemode_changelist"))
    assert response.status_code == 200
    assert MaintenanceMode.objects.count() == 1
    assert admin_client.get(reverse("admin:core_maintenancemode_add")).status_code == 403
    row = MaintenanceMode.load()
    delete_url = reverse("admin:core_maintenancemode_delete", args=[row.pk])
    assert admin_client.get(delete_url).status_code == 403

    change_url = reverse("admin:core_maintenancemode_change", args=[row.pk])
    assert admin_client.post(change_url, {"enabled": "on"}).status_code == 302
    assert DatabaseStateBackend().get_value() is True
