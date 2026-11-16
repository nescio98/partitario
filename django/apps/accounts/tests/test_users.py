"""The user model: an email address instead of a username, a UUID as key."""

import uuid

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import authenticate
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

PASSWORD = "a-long-passphrase-1"


@pytest.mark.django_db
def test_the_key_is_a_uuid_and_there_is_no_username_or_name(django_user_model):
    user = django_user_model.objects.create_user("simone@example.com", PASSWORD)
    assert isinstance(user.pk, uuid.UUID)
    assert user.get_username() == "simone@example.com"
    fields = {field.name for field in django_user_model._meta.get_fields()}
    assert fields.isdisjoint({"username", "first_name", "last_name"})


@pytest.mark.django_db
def test_create_user_lowers_the_address(django_user_model):
    assert django_user_model.objects.create_user(" Simone@Example.COM ", PASSWORD).email == (
        "simone@example.com"
    )
    assert django_user_model.objects.create_superuser("ROOT@example.com", PASSWORD).email == (
        "root@example.com"
    )
    assert authenticate(email="Simone@example.com", password=PASSWORD) is not None


@pytest.mark.django_db
def test_a_user_needs_an_address(django_user_model):
    with pytest.raises(ValueError, match="email address"):
        django_user_model.objects.create_user("", PASSWORD)


@pytest.mark.django_db
def test_createsuperuser_makes_a_user_who_can_log_in_at_once(django_user_model, monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", PASSWORD)
    call_command("createsuperuser", "--noinput", "--email", "Admin@Example.com")
    user = django_user_model.objects.get()
    assert user.email == "admin@example.com"
    # No confirmation mail to wait for: the address counts as verified.
    assert EmailAddress.objects.get(user=user, email="admin@example.com").verified


@pytest.mark.django_db
def test_the_database_refuses_a_duplicate_address_whatever_its_casing(django_user_model):
    user = django_user_model.objects.create_user("same@example.com", PASSWORD)
    with pytest.raises(IntegrityError), transaction.atomic():
        django_user_model.objects.create_user("SAME@example.com", PASSWORD)
    # Past Django (bulk_create, update()), the constraint refuses capitals.
    with pytest.raises(IntegrityError), transaction.atomic():
        django_user_model.objects.filter(pk=user.pk).update(email="Same@example.com")


def add_user(client, email):
    return client.post(
        reverse("admin:accounts_user_add"),
        {"email": email, "usable_password": "true", "password1": PASSWORD, "password2": PASSWORD},
    )


def test_the_admin_lowers_the_address_and_tells_allauth(admin_client, django_user_model):
    assert add_user(admin_client, "NewUser@Example.com").status_code == 302
    user = django_user_model.objects.get(email="newuser@example.com")
    # Unverified: its owner confirms it at the first login.
    assert not EmailAddress.objects.get(user=user).verified


def test_the_admin_refuses_an_address_already_in_use(admin_client, create_user, django_user_model):
    create_user("taken@example.com")
    assert add_user(admin_client, "Taken@Example.com").status_code == 200
    assert django_user_model.objects.count() == 2  # the admin and "taken"


def test_an_address_changed_in_the_admin_replaces_the_old_one(admin_client, create_user):
    user = create_user("old@example.com")
    change_url = reverse("admin:accounts_user_change", args=[user.pk])
    data = {
        "email": "new@example.com",
        "is_active": "on",
        "last_login_0": "",
        "last_login_1": "",
        "date_joined_0": "16/11/2026",
        "date_joined_1": "10:00:00",
    }
    assert admin_client.post(change_url, data).status_code == 302
    # The old address no longer logs anybody in; the new one waits for its owner.
    assert list(EmailAddress.objects.filter(user=user).values_list("email", "verified")) == [
        ("new@example.com", False)
    ]
