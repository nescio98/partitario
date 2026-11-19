"""Two-factor authentication: asked at login, mandatory for staff."""

import logging

import pytest
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
    yield_hotp_counters_from_time,
)
from django.urls import reverse

PASSWORD = "a-long-passphrase-1"


@pytest.fixture
def staff(create_user):
    return create_user("staff@example.com", is_staff=True)


@pytest.fixture
def totp_secret(staff):
    secret = generate_totp_secret()
    TOTP.activate(staff, secret)
    return secret


def current_code(secret):
    return format_hotp_value(hotp_value(secret, next(yield_hotp_counters_from_time())))


def log_in(client, email):
    return client.post(reverse("account_login"), {"login": email, "password": PASSWORD})


def confirm_password(client):
    """Changing the second factor asks for the password again, even right after login."""
    return client.post(reverse("account_reauthenticate"), {"password": PASSWORD})


def test_the_password_alone_does_not_log_in(client, staff, totp_secret, caplog):
    response = log_in(client, "staff@example.com")
    assert response.status_code == 302
    assert response["Location"] == reverse("mfa_authenticate")
    assert "_auth_user_id" not in client.session
    assert client.get(reverse("mfa_authenticate")).status_code == 200

    with caplog.at_level(logging.WARNING, logger="apps.accounts.signals"):
        response = client.post(reverse("mfa_authenticate"), {"code": "000000"})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert "Two-factor code rejected for staff@example.com" in caplog.text

    response = client.post(reverse("mfa_authenticate"), {"code": current_code(totp_secret)})
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(staff.pk)


def test_staff_without_a_second_factor_are_sent_to_set_it_up(client, staff, settings):
    settings.STAFF_MFA_REQUIRED = True
    assert log_in(client, "staff@example.com").status_code == 302
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert response["Location"] == reverse("mfa_index")
    # The pages needed to comply, or to leave, stay reachable.
    assert client.get(reverse("mfa_index")).status_code == 200
    assert client.get(reverse("account_reauthenticate")).status_code == 200
    confirm_password(client)
    assert client.get(reverse("mfa_activate_totp")).status_code == 200
    assert client.get(reverse("account_logout")).status_code == 200


def test_staff_with_a_second_factor_pass(client, staff, totp_secret, settings):
    settings.STAFF_MFA_REQUIRED = True
    client.force_login(staff)
    assert client.get(reverse("admin:index")).status_code == 200


def test_ordinary_users_are_not_forced(client, create_user, settings):
    settings.STAFF_MFA_REQUIRED = True
    client.force_login(create_user("member@example.com"))
    assert client.get(reverse("account_change_password")).status_code == 200
    # Not staff: refused by the admin, not redirected to the second factor.
    assert client.get(reverse("admin:index"), follow=True).status_code == 403


def test_impersonation_relies_on_the_second_factor_of_the_superuser(
    admin_client, admin_user, staff, settings
):
    TOTP.activate(admin_user, generate_totp_secret())
    settings.STAFF_MFA_REQUIRED = True
    admin_client.post(reverse("hijack:acquire"), {"user_pk": staff.pk, "next": "/"})
    assert admin_client.session["_auth_user_id"] == str(staff.pk)
    assert admin_client.get(reverse("admin:index")).status_code == 200


# A real transaction: allauth logs and mails once the new authenticator is committed.
@pytest.mark.django_db(transaction=True)
def test_setting_up_an_authenticator_app_is_logged_and_notified(client, staff, caplog, mailoutbox):
    log_in(client, "staff@example.com")
    assert client.get(reverse("mfa_activate_totp")).status_code == 302  # password, again
    confirm_password(client)
    page = client.get(reverse("mfa_activate_totp"))
    assert page.status_code == 200
    secret = page.context["form"].secret
    with caplog.at_level(logging.WARNING, logger="apps.accounts.signals"):
        response = client.post(reverse("mfa_activate_totp"), {"code": current_code(secret)})
    assert response.status_code == 302
    assert f"staff@example.com (id {staff.pk}) added totp" in caplog.text
    assert [mail.to for mail in mailoutbox] == [["staff@example.com"]]
