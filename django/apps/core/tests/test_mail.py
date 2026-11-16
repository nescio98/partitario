"""Mail is queued as a task and delivered by it, through the real mailer."""

import io
import logging
from datetime import timedelta

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives, send_mail
from django.urls import reverse
from django.utils import timezone
from django_tasks_db.models import DBTaskResult

from apps.core import tasks
from apps.core.mail import ConsoleEmailBackend, deserialize, serialize

DATABASE = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}


@pytest.fixture
def queued_mail(settings):
    """The production wiring, with the outbox of the tests as the mail server."""
    settings.MAILERS = {
        "default": {"BACKEND": "apps.core.mail.QueuedEmailBackend"},
        "transport": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
    }


def test_a_message_survives_the_queue():
    message = EmailMultiAlternatives(
        subject="Report",
        body="Plain text",
        from_email="app@example.com",
        to=["one@example.com"],
        cc=["two@example.com"],
        bcc=["three@example.com"],
        reply_to=["reply@example.com"],
        headers={"X-Tag": "report"},
    )
    message.attach_alternative("<p>HTML</p>", "text/html")
    message.attach("notes.txt", "some notes", "text/plain")
    message.attach("data.bin", b"\x00\x01\xff", "application/octet-stream")

    copy = deserialize(serialize(message))

    assert (copy.subject, copy.body, copy.from_email) == ("Report", "Plain text", "app@example.com")
    assert (copy.to, copy.cc, copy.bcc) == (
        ["one@example.com"],
        ["two@example.com"],
        ["three@example.com"],
    )
    assert copy.reply_to == ["reply@example.com"]
    assert copy.extra_headers == {"X-Tag": "report"}
    assert [tuple(alternative) for alternative in copy.alternatives] == [
        ("<p>HTML</p>", "text/html")
    ]
    assert [tuple(attachment) for attachment in copy.attachments] == [
        ("notes.txt", "some notes", "text/plain"),
        ("data.bin", b"\x00\x01\xff", "application/octet-stream"),
    ]


@pytest.mark.django_db
def test_under_debug_mail_is_delivered_at_once(queued_mail):
    send_mail("Hello", "Body", "app@example.com", ["one@example.com"])
    assert [message.subject for message in mail.outbox] == ["Hello"]


@pytest.mark.django_db
def test_with_a_worker_the_request_only_queues(queued_mail, settings, client, django_user_model):
    settings.TASKS = DATABASE
    django_user_model.objects.create_user("member@example.com", "a-long-passphrase-1")

    response = client.post(reverse("account_reset_password"), {"email": "member@example.com"})

    assert response.status_code == 302
    assert mail.outbox == []
    queued = DBTaskResult.objects.get()
    assert queued.task_path == "apps.core.tasks.deliver_mail"
    assert queued.status == "READY"

    # What the worker does with the row.
    tasks.deliver_mail.func(*queued.args_kwargs["args"], **queued.args_kwargs["kwargs"])
    assert [message.to for message in mail.outbox] == [["member@example.com"]]


@pytest.mark.django_db
def test_a_failed_delivery_is_tried_again_later_then_given_up(settings, caplog):
    settings.TASKS = DATABASE
    settings.MAILERS = {
        "default": {"BACKEND": "apps.core.mail.QueuedEmailBackend"},
        # Nothing listens on port 1.
        "transport": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {"host": "127.0.0.1", "port": 1, "timeout": 2},
        },
    }
    message = serialize(EmailMultiAlternatives("Hello", "Body", "a@example.com", ["b@example.com"]))

    with caplog.at_level(logging.WARNING, logger="apps.core.tasks"):
        tasks.deliver_mail.func(message)
    retry = DBTaskResult.objects.get()
    assert retry.args_kwargs["args"][1] == 2
    assert retry.run_after > timezone.now() + timedelta(seconds=30)
    assert "trying again" in caplog.text

    last_attempt = len(tasks.MAIL_RETRY_DELAYS) + 1
    with (
        pytest.raises(ConnectionRefusedError),
        caplog.at_level(logging.ERROR, logger="apps.core.tasks"),
    ):
        tasks.deliver_mail.func(message, last_attempt)
    assert DBTaskResult.objects.count() == 1
    assert "giving up" in caplog.text


def test_the_task_list_is_for_superusers_only(admin_client, client, django_user_model):
    url = reverse("admin:django_tasks_database_dbtaskresult_changelist")
    assert admin_client.get(url).status_code == 200
    staff = django_user_model.objects.create_user(
        "staff@example.com", "a-long-passphrase-1", is_staff=True
    )
    client.force_login(staff)
    assert client.get(url).status_code == 403


def test_without_a_mail_server_a_long_link_is_printed_in_one_piece():
    """Django's console backend prints what travels: lines cut at 76
    characters with a trailing `=`, so a copied link is a 404."""
    link = "http://localhost:8000/accounts/password/reset/key/" + "a" * 60 + "/"
    log = io.StringIO()
    message = EmailMultiAlternatives("Reset", f"Follow\n{link}\n", "app@example.com", ["x@y.it"])
    message.attach("report.csv", "a;b\n", "text/csv")

    assert ConsoleEmailBackend(stream=log).send_messages([message]) == 1

    printed = log.getvalue()
    assert link in printed.splitlines()
    assert "To: x@y.it" in printed
    assert "Subject: Reset" in printed
    assert "Attachment: report.csv" in printed
