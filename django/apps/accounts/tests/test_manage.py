"""The account page: the way to allauth's pages, and leaving."""

import logging

import pytest
from django.urls import reverse

PASSWORD = "a-long-passphrase-1"


@pytest.fixture
def member(create_user):
    return create_user("member@example.com")


@pytest.fixture
def member_client(client, member):
    """Logged in, and past the second request for the password that every
    change to the account starts with."""
    client.force_login(member)
    client.post(reverse("account_reauthenticate"), {"password": PASSWORD})
    return client


@pytest.mark.django_db
def test_the_account_page_needs_a_login(client):
    response = client.get(reverse("account_manage"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_login"))


def test_the_account_page_leads_to_every_other_one(member_client):
    response = member_client.get(reverse("account_manage"))
    assert response.status_code == 200
    page = response.content.decode()
    assert "unfold/css/styles.css" in page
    assert "member@example.com" in page
    for name in (
        "account_email",
        "account_change_password",
        "mfa_index",
        "usersessions_list",
        "account_delete",
        "account_logout",
    ):
        assert reverse(name) in page


def test_the_account_page_changes_nothing_itself(member_client, member):
    response = member_client.post(
        reverse("account_manage"), {"is_staff": "on", "email": "x@example.com"}
    )
    assert response.status_code == 200
    member.refresh_from_db()
    assert (member.is_staff, member.email) == (False, "member@example.com")


def test_a_user_changes_their_address_once_the_new_one_is_confirmed(
    member_client, member, mailoutbox
):
    response = member_client.post(
        reverse("account_email"), {"action_add": "", "email": "new@example.com"}
    )
    assert response["Location"] == reverse("account_email")
    member.refresh_from_db()
    assert member.email == "member@example.com"  # until the link is followed
    assert ["new@example.com"] in [mail.to for mail in mailoutbox]


def test_a_user_deletes_their_account_and_it_is_logged(
    member_client, member, django_user_model, caplog
):
    assert member_client.get(reverse("account_delete")).status_code == 200
    assert django_user_model.objects.filter(pk=member.pk).exists()  # a GET deletes nothing
    with caplog.at_level(logging.WARNING, logger="apps.accounts.services"):
        response = member_client.post(reverse("account_delete"))
    assert response["Location"] == reverse("account_login")
    assert not django_user_model.objects.filter(pk=member.pk).exists()
    assert "_auth_user_id" not in member_client.session
    assert f"member@example.com (id {member.pk})" in caplog.text


def test_deleting_asks_for_the_password_again(client, member, django_user_model):
    client.force_login(member)  # a session whose password was not just typed
    response = client.post(reverse("account_delete"))
    assert response["Location"].startswith(reverse("account_reauthenticate"))
    assert django_user_model.objects.filter(pk=member.pk).exists()


def test_a_superuser_cannot_delete_themselves(admin_client, admin_user, django_user_model):
    admin_client.post(reverse("account_reauthenticate"), {"password": "password"})
    assert reverse("account_delete") not in admin_client.get(reverse("account_manage")).text
    assert admin_client.post(reverse("account_delete")).status_code == 403
    assert django_user_model.objects.filter(pk=admin_user.pk).exists()


def test_nobody_is_deleted_while_impersonated(admin_client, member, django_user_model):
    admin_client.post(reverse("account_reauthenticate"), {"password": "password"})
    admin_client.post(reverse("hijack:acquire"), {"user_pk": member.pk, "next": "/"})
    assert admin_client.post(reverse("account_delete")).status_code == 403
    assert django_user_model.objects.filter(pk=member.pk).exists()
