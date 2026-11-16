"""Signup: open, behind Turnstile, and nobody gets in before confirming their address."""

import io
import re

import pytest
from allauth.account.models import EmailAddress
from django.core.checks import Error
from django.urls import reverse

from apps.accounts import turnstile
from apps.accounts.checks import turnstile_keys

PASSWORD = "a-long-passphrase-1"


def sign_up(client, email="new@example.com", **extra):
    return client.post(
        reverse("account_signup"),
        {"email": email, "password1": PASSWORD, "password2": PASSWORD, **extra},
    )


def log_in(client, email):
    return client.post(reverse("account_login"), {"login": email, "password": PASSWORD})


def confirmation_link(mail):
    return re.findall(r"https?://\S+/accounts/confirm-email/\S+", mail.body)[0]


@pytest.mark.django_db
def test_signing_up_asks_to_confirm_the_address_before_anything_else(
    client, django_user_model, mailoutbox
):
    response = sign_up(client, "New@Example.com")
    assert response.status_code == 302
    assert response["Location"] == reverse("account_email_verification_sent")
    user = django_user_model.objects.get(email="new@example.com")
    assert (user.is_staff, user.is_superuser) == (False, False)
    assert "_auth_user_id" not in client.session
    assert [mail.to for mail in mailoutbox] == [["new@example.com"]]

    # The password alone does not log in: the mail is sent again instead.
    assert log_in(client, "new@example.com")["Location"] == reverse(
        "account_email_verification_sent"
    )
    assert "_auth_user_id" not in client.session

    link = confirmation_link(mailoutbox[0])
    assert client.get(link).status_code == 200  # a page with a button, no change yet
    assert client.post(link).status_code == 302
    assert EmailAddress.objects.get(user=user).verified
    assert log_in(client, "new@example.com").status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_signing_up_with_a_registered_address_tells_only_its_owner(
    client, create_user, django_user_model, mailoutbox
):
    create_user("member@example.com")
    response = sign_up(client, "member@example.com")
    # Same answer as for a new address; the owner gets a mail saying so.
    assert response["Location"] == reverse("account_email_verification_sent")
    assert django_user_model.objects.count() == 1
    assert [mail.to for mail in mailoutbox] == [["member@example.com"]]


@pytest.mark.django_db
def test_a_user_created_in_the_admin_confirms_the_address_at_the_first_login(
    client, create_user, mailoutbox
):
    create_user("invited@example.com", verified=False)
    assert log_in(client, "invited@example.com")["Location"] == reverse(
        "account_email_verification_sent"
    )
    assert "_auth_user_id" not in client.session
    assert [mail.to for mail in mailoutbox] == [["invited@example.com"]]


@pytest.mark.django_db
def test_signup_can_be_closed(client, django_user_model, settings):
    settings.ACCOUNT_SIGNUP_OPEN = False
    assert sign_up(client).status_code == 200
    assert not django_user_model.objects.exists()
    assert reverse("account_signup") not in client.get(reverse("account_login")).content.decode()


@pytest.fixture
def captcha(settings, monkeypatch):
    """The Turnstile field is on; Cloudflare answers what the test says."""
    settings.TURNSTILE_ENABLED = True
    asked: list[str] = []
    answers = {"valid": True, "asked": asked}

    def verify(token):
        asked.append(token)
        return answers["valid"]

    monkeypatch.setattr(turnstile, "verify", verify)
    return answers


@pytest.mark.django_db
def test_the_signup_form_shows_the_widget(client, captcha, settings):
    page = client.get(reverse("account_signup")).content.decode()
    assert f'class="cf-turnstile" data-sitekey="{settings.TURNSTILE_SITE_KEY}"' in page
    assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in page


@pytest.mark.django_db
def test_signup_without_a_token_cloudflare_accepts_creates_nobody(
    client, captcha, django_user_model
):
    assert sign_up(client).status_code == 200  # no token: Cloudflare is not even asked
    assert captcha["asked"] == []
    captcha["valid"] = False
    assert sign_up(client, **{"cf-turnstile-response": "from-a-bot"}).status_code == 200
    assert not django_user_model.objects.exists()

    captcha["valid"] = True
    assert sign_up(client, **{"cf-turnstile-response": "from-a-person"}).status_code == 302
    assert captcha["asked"] == ["from-a-bot", "from-a-person"]
    assert django_user_model.objects.count() == 1


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_verifying_a_token_posts_it_to_cloudflare_with_the_secret(settings, monkeypatch):
    settings.TURNSTILE_SECRET_KEY = "the-secret"
    sent: dict[str, object] = {}

    def urlopen(url, data, timeout):
        sent.update(url=url, data=data.decode(), timeout=timeout)
        return Answer(b'{"success": true}')

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert turnstile.verify("a-token") is True
    assert sent == {
        "url": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        "data": "secret=the-secret&response=a-token",
        "timeout": 5,
    }


@pytest.mark.parametrize(
    "answer",
    [
        b'{"success": false, "error-codes": ["invalid-input-response"]}',
        b"not json",
        OSError("no route to Cloudflare"),
    ],
)
def test_a_refusal_or_an_outage_lets_nobody_through(monkeypatch, answer):
    def urlopen(url, data, timeout):
        if isinstance(answer, Exception):
            raise answer
        return Answer(answer)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert turnstile.verify("a-token") is False


@pytest.mark.parametrize(
    ("env", "enabled", "refused"),
    [
        ("dev", True, False),
        ("staging", True, False),
        ("prod", True, True),
        ("selfhost", True, True),
        ("prod", False, False),
    ],
)
def test_the_test_keys_are_refused_where_real_people_sign_up(settings, env, enabled, refused):
    settings.ENV = env
    settings.TURNSTILE_ENABLED = enabled
    errors = turnstile_keys(None)
    assert [type(error) for error in errors] == ([Error] if refused else [])

    settings.TURNSTILE_SITE_KEY = "<site key>"  # the env template, not filled in
    settings.TURNSTILE_SECRET_KEY = "<secret key>"
    assert [type(error) for error in turnstile_keys(None)] == ([Error] if refused else [])

    settings.TURNSTILE_SITE_KEY = "site-key-of-this-site"
    settings.TURNSTILE_SECRET_KEY = "secret-key-of-this-site"
    assert turnstile_keys(None) == []
