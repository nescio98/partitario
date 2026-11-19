"""Impersonation from the admin: who may do it, and that it leaves a trace."""

import logging

import pytest
from django.urls import reverse

from apps.accounts.permissions import can_hijack


@pytest.fixture
def member(django_user_model):
    return django_user_model.objects.create_user("member@example.com", "a-long-passphrase-1")


def test_superuser_can_act_as_a_user_and_it_is_logged(admin_client, admin_user, member, caplog):
    with caplog.at_level(logging.WARNING, logger="apps.accounts.signals"):
        response = admin_client.post(reverse("hijack:acquire"), {"user_pk": member.pk, "next": "/"})
    assert response.status_code == 302
    assert admin_client.session["_auth_user_id"] == str(member.pk)
    assert f"{admin_user.email} (id {admin_user.pk}) is acting as member@example.com" in caplog.text

    with caplog.at_level(logging.WARNING, logger="apps.accounts.signals"):
        admin_client.post(reverse("hijack:release"), {"next": "/"})
    assert admin_client.session["_auth_user_id"] == str(admin_user.pk)
    assert "Impersonation ended" in caplog.text


def test_a_superuser_cannot_act_as_another_superuser(admin_client, django_user_model):
    other = django_user_model.objects.create_superuser("other@example.com", "a-long-passphrase-1")
    response = admin_client.post(reverse("hijack:acquire"), {"user_pk": other.pk})
    assert response.status_code == 403


def test_staff_and_ordinary_users_cannot_impersonate(client, django_user_model, member):
    staff = django_user_model.objects.create_user(
        "staff@example.com", "a-long-passphrase-1", is_staff=True
    )
    client.force_login(staff)
    assert client.post(reverse("hijack:acquire"), {"user_pk": member.pk}).status_code == 403


@pytest.mark.django_db
def test_inactive_users_cannot_be_impersonated(admin_user, member):
    member.is_active = False
    assert can_hijack(hijacker=admin_user, hijacked=member) is False
    assert can_hijack(hijacker=admin_user, hijacked=None) is False


def test_the_user_list_offers_the_button(admin_client, member):
    response = admin_client.get(reverse("admin:accounts_user_changelist"))
    assert response.status_code == 200
    assert f'data-hijack-user="{member.pk}"' in response.content.decode()
