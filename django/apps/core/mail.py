"""Mail leaves the request: the default mailer only queues, a task delivers.

`MAILERS["default"]` is `QueuedEmailBackend`, so everything that sends mail
the usual way (`send_mail`, `EmailMessage.send()`, allauth) returns at once and
a slow or unreachable mail server never holds up a page. The task
(`apps.core.tasks.deliver_mail`) sends through `MAILERS["transport"]`, the real
one (SMTP, or `ConsoleEmailBackend` below without `EMAIL_HOST`).
"""

import base64
from collections.abc import Sequence
from typing import Any

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as DjangoConsoleEmailBackend

TRANSPORT_MAILER = "transport"


def serialize(message: EmailMessage) -> dict[str, Any]:
    """The message as JSON-compatible data, to travel as a task argument."""
    attachments = []
    for attachment in message.attachments:
        if not isinstance(attachment, tuple):
            raise TypeError(
                "Queued mail takes attachments as (filename, content, mimetype), "
                f"not {type(attachment).__name__}"
            )
        filename, content, mimetype = attachment
        binary = isinstance(content, bytes)
        attachments.append(
            {
                "filename": filename,
                "content": base64.b64encode(content).decode("ascii") if binary else content,
                "mimetype": mimetype,
                "binary": binary,
            }
        )
    return {
        "subject": str(message.subject),
        "body": str(message.body),
        "content_subtype": message.content_subtype,
        "from_email": message.from_email,
        "to": list(message.to),
        "cc": list(message.cc),
        "bcc": list(message.bcc),
        "reply_to": list(message.reply_to),
        "headers": {name: str(value) for name, value in message.extra_headers.items()},
        "alternatives": [
            [str(content), mimetype] for content, mimetype in getattr(message, "alternatives", [])
        ],
        "attachments": attachments,
    }


def deserialize(data: dict[str, Any]) -> EmailMultiAlternatives:
    message = EmailMultiAlternatives(
        subject=data["subject"],
        body=data["body"],
        from_email=data["from_email"],
        to=data["to"],
        cc=data["cc"],
        bcc=data["bcc"],
        reply_to=data["reply_to"],
        headers=data["headers"],
    )
    message.content_subtype = data["content_subtype"]
    for content, mimetype in data["alternatives"]:
        message.attach_alternative(content, mimetype)
    for attachment in data["attachments"]:
        content = attachment["content"]
        if attachment["binary"]:
            content = base64.b64decode(content)
        message.attach(attachment["filename"], content, attachment["mimetype"])
    return message


class QueuedEmailBackend(BaseEmailBackend):
    """Hand each message to the task queue instead of a mail server."""

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        from .tasks import deliver_mail

        for message in email_messages:
            deliver_mail.enqueue(serialize(message))
        return len(email_messages)


class ConsoleEmailBackend(DjangoConsoleEmailBackend):
    """Print a mail the way its reader sees it, for when there is no mail server.

    Django's console backend prints the message as it travels: long lines are
    cut at 76 characters with a trailing `=` (quoted-printable), which breaks
    every link - a password reset or a confirmation - when copied from the
    log. Here the text is printed as written, under the headers that matter.
    """

    def write_message(self, message: EmailMessage) -> None:
        lines = [f"From: {message.from_email}", f"To: {', '.join(message.to)}"]
        if message.cc:
            lines.append(f"Cc: {', '.join(message.cc)}")
        if message.bcc:
            lines.append(f"Bcc: {', '.join(message.bcc)}")
        lines.append(f"Subject: {message.subject}")
        for attachment in message.attachments:
            name = attachment[0] if isinstance(attachment, tuple) else attachment.get_filename()
            lines.append(f"Attachment: {name}")
        self.stream.write("\n".join(lines))
        self.stream.write(f"\n\n{message.body}\n")
        self.stream.write("-" * 79 + "\n")
