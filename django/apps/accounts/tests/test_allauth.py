"""The account pages: one login for everybody, by email address; password reset."""

import logging

import pytest
from django.contrib.auth import authenticate
from django.test import Client
from django.urls import reverse

PASSWORD = "a-long-passphrase-1"


@pytest.fixture
def member(create_user):
    return create_user("member@example.com")


def log_in(client, email, password=PASSWORD):
    return client.post(reverse("account_login"), {"login": email, "password": password})


@pytest.mark.django_db
def test_login_page_renders_in_the_admin_layout(client):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200
    page = response.content.decode()
    assert "unfold/css/styles.css" in page
    assert "css/app.css" in page
    assert reverse("account_signup") in page
    assert reverse("account_reset_password") in page


@pytest.mark.django_db
def test_the_admin_login_is_the_allauth_login(client):
    response = client.get(reverse("admin:index"), follow=True)
    assert response.redirect_chain[-1][0].startswith(reverse("account_login"))
    # Posting credentials to the admin's own form logs nobody in.
    response = client.post(reverse("admin:login"), {"username": "x", "password": "y"})
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_login"))


def test_login_and_logout_are_logged(client, member, caplog):
    with caplog.at_level(logging.INFO, logger="apps.accounts.signals"):
        assert log_in(client, "member@example.com").status_code == 302
        client.post(reverse("account_logout"))
    assert f"Login: member@example.com (id {member.pk}) from 127.0.0.1" in caplog.text
    assert f"Logout: member@example.com (id {member.pk})" in caplog.text


def test_a_failed_login_is_logged(client, member, caplog):
    with caplog.at_level(logging.WARNING, logger="apps.accounts.signals"):
        response = log_in(client, "member@example.com", "wrong")
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
    assert "Login failed for 'member@example.com' from 127.0.0.1" in caplog.text


def test_repeated_failures_lock_the_address_out(client, member):
    for _ in range(5):
        log_in(client, "member@example.com", "wrong")
    # The right password does not help until the limit expires.
    assert log_in(client, "member@example.com").status_code == 200
    assert "_auth_user_id" not in client.session


def test_login_accepts_any_casing_of_the_address(client, member):
    assert log_in(client, "MEMBER@Example.com").status_code == 302
    assert client.session["_auth_user_id"] == str(member.pk)
    assert authenticate(email="Member@example.com", password=PASSWORD) == member


def test_there_is_no_login_by_anything_but_the_address(client, member):
    assert log_in(client, "member").status_code == 200
    assert "_auth_user_id" not in client.session


def test_a_login_lands_on_the_account_page_or_the_admin(client, member, admin_client):
    log_in(client, "member@example.com")
    assert client.get(reverse("home"))["Location"] == reverse("account_manage")
    assert admin_client.get(reverse("home"))["Location"] == reverse("admin:index")


def test_password_reset_sends_a_mail(client, member, mailoutbox):
    response = client.post(reverse("account_reset_password"), {"email": "member@example.com"})
    assert response.status_code == 302
    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject.startswith("[partitario] ")


@pytest.mark.django_db
def test_password_reset_writes_to_nobody_it_does_not_know(client, mailoutbox):
    response = client.post(reverse("account_reset_password"), {"email": "stranger@example.com"})
    # Same answer as for a known address, but no mail leaves.
    assert response.status_code == 302
    assert mailoutbox == []


def test_a_password_change_is_notified_by_mail(client, member, mailoutbox):
    log_in(client, "member@example.com")
    response = client.post(
        reverse("account_change_password"),
        {
            "oldpassword": PASSWORD,
            "password1": "another-long-phrase-2",
            "password2": "another-long-phrase-2",
        },
    )
    assert response.status_code == 302
    assert [mail.to for mail in mailoutbox] == [["member@example.com"]]


def test_a_user_sees_their_sessions_and_ends_the_others(client, member):
    elsewhere = Client()
    log_in(elsewhere, "member@example.com")
    log_in(client, "member@example.com")
    page = client.get(reverse("usersessions_list"))
    assert page.status_code == 200
    assert page.context["session_count"] == 2

    assert client.post(reverse("usersessions_list")).status_code == 302
    assert "_auth_user_id" in client.session
    assert "_auth_user_id" not in elsewhere.session
