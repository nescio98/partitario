"""Background tasks (Django's tasks framework, settings.TASKS).

Outside DEBUG a task is a row in the database, run by the `worker` container
(`manage.py db_worker`); under DEBUG and in tests it runs at once, in the
caller. Define a project's tasks the same way, in `apps/<app>/tasks.py`:
arguments and results must be JSON, so pass ids, not objects.
"""

import logging
from datetime import timedelta
from typing import Any

from django.core.mail import mailers
from django.tasks import task
from django.utils import timezone

from .mail import TRANSPORT_MAILER, deserialize

logger = logging.getLogger(__name__)

# A mail server that is down gets two more tries, one and ten minutes later.
MAIL_RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=10))


@task
def deliver_mail(message: dict[str, Any], attempt: int = 1) -> None:
    """Send one queued message (apps/core/mail.py) through the real mailer."""
    email = deserialize(message)
    try:
        mailers[TRANSPORT_MAILER].send_messages([email])
    except Exception:
        can_retry = attempt <= len(MAIL_RETRY_DELAYS) and deliver_mail.get_backend().supports_defer
        if not can_retry:
            logger.exception("Mail %r to %s not sent, giving up", email.subject, email.to)
            raise
        delay = MAIL_RETRY_DELAYS[attempt - 1]
        logger.warning(
            "Mail %r to %s not sent (attempt %s), trying again in %s",
            email.subject,
            email.to,
            attempt,
            delay,
            exc_info=True,
        )
        deliver_mail.using(run_after=timezone.now() + delay).enqueue(message, attempt + 1)
