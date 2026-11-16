"""The user admin: the second factor at a glance and its reset."""

import logging

import pytest
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.contrib.auth.models import Permission
from django.urls import reverse

PASSWORD = "a-long-passphrase-1"


@pytest.fixture
def member(create_user):
    user = create_user("member@example.com")
    TOTP.activate(user, generate_totp_secret())
    return user


def reset(client, *users):
    return client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "reset_two_factor", "_selected_action": [user.pk for user in users]},
    )


def test_a_superuser_resets_a_lost_second_factor_and_it_is_logged(
    admin_client, admin_user, member, caplog
):
    with caplog.at_level(logging.WARNING, logger="apps.accounts.services"):
        assert reset(admin_client, member).status_code == 302
    assert not Authenticator.objects.filter(user=member).exists()
    assert (
        f"Two-factor authentication of member@example.com (id {member.pk}) "
        f"reset by {admin_user.email} (id {admin_user.pk})"
    ) in caplog.text


def test_staff_cannot_reset_a_second_factor(client, django_user_model, member):
    staff = django_user_model.objects.create_user("staff@example.com", PASSWORD, is_staff=True)
    staff.user_permissions.set(Permission.objects.filter(content_type__app_label="accounts"))
    client.force_login(staff)
    page = client.get(reverse("admin:accounts_user_changelist"))
    assert page.status_code == 200
    assert "reset_two_factor" not in page.content.decode()
    reset(client, member)
    assert Authenticator.objects.filter(user=member).exists()


def test_the_user_list_shows_who_has_a_second_factor(admin_client, member):
    page = admin_client.get(reverse("admin:accounts_user_changelist"))
    assert page.status_code == 200
    rows = {user.email: user.has_two_factor for user in page.context["cl"].result_list}
    assert rows == {"member@example.com": True, "admin@example.com": False}
