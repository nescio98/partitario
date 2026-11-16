"""Every account page renders in the project's layout, and the flows that
travel by mail (password reset, change of address) work end to end."""

import re

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse

PASSWORD = "a-long-passphrase-1"
NEW_PASSWORD = "another-long-phrase-2"


@pytest.fixture
def member(create_user):
    return create_user("member@example.com")


def log_in(client, email, password=PASSWORD):
    return client.post(reverse("account_login"), {"login": email, "password": password})


def link_in(mail, path):
    return re.findall(rf"https?://\S+{path}\S+", mail.body)[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name",
    [
        "account_login",
        "account_signup",
        "account_reset_password",
        "account_reset_password_done",
        "account_email_verification_sent",
        "account_inactive",
    ],
)
def test_pages_for_visitors_render(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 200
    assert "unfold/css/styles.css" in response.text


@pytest.mark.parametrize(
    "name",
    [
        "account_manage",
        "account_delete",
        "account_email",
        "account_change_password",
        "account_reauthenticate",
        "mfa_index",
        "mfa_activate_totp",
        "usersessions_list",
        "account_logout",
    ],
)
def test_pages_for_users_render(client, member, name):
    client.force_login(member)
    client.post(reverse("account_reauthenticate"), {"password": PASSWORD})
    response = client.get(reverse(name))
    assert response.status_code == 200
    assert "unfold/css/styles.css" in response.text


@pytest.mark.django_db
def test_the_closed_signup_page_renders(client, settings):
    settings.ACCOUNT_SIGNUP_OPEN = False
    response = client.get(reverse("account_signup"))
    assert response.status_code == 200
    assert "unfold/css/styles.css" in response.text


def test_the_user_pages_of_the_admin_render(admin_client, member):
    for url in (
        reverse("admin:accounts_user_changelist") + "?q=member",
        reverse("admin:accounts_user_add"),
        reverse("admin:accounts_user_change", args=[member.pk]),
        reverse("admin:auth_user_password_change", args=[member.pk]),
    ):
        assert admin_client.get(url).status_code == 200, url


def test_a_forgotten_password_is_reset_through_the_mailed_link(client, member, mailoutbox):
    client.post(reverse("account_reset_password"), {"email": "Member@example.com"})
    link = link_in(mailoutbox[0], "/accounts/password/reset/key/")
    # The link is long (the user's key is a UUID): it must be on one line.
    assert link in mailoutbox[0].body.splitlines()

    form = client.get(link, follow=True)
    assert form.status_code == 200
    response = client.post(
        form.redirect_chain[-1][0], {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD}
    )
    assert response.status_code == 302
    assert log_in(client, "member@example.com", PASSWORD).status_code == 200  # the old one is gone
    assert log_in(client, "member@example.com", NEW_PASSWORD).status_code == 302
    assert client.session["_auth_user_id"] == str(member.pk)


def test_a_new_address_replaces_the_old_one_once_confirmed(client, member, mailoutbox):
    client.force_login(member)
    client.post(reverse("account_reauthenticate"), {"password": PASSWORD})
    client.post(reverse("account_email"), {"action_add": "", "email": "new@example.com"})
    confirmation = next(mail for mail in mailoutbox if mail.to == ["new@example.com"])
    assert client.post(link_in(confirmation, "/accounts/confirm-email/")).status_code == 302

    member.refresh_from_db()
    assert member.email == "new@example.com"
    assert list(EmailAddress.objects.filter(user=member).values_list("email", "verified")) == [
        ("new@example.com", True)
    ]
    client.post(reverse("account_logout"))
    assert log_in(client, "new@example.com").status_code == 302
    client.post(reverse("account_logout"))
    # The old address no longer logs anybody in.
    assert log_in(client, "member@example.com").status_code == 200
    assert "_auth_user_id" not in client.session
