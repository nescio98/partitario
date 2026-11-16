"""Writes on accounts that are more than saving a form."""

import logging

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.db import transaction

from .models import User

logger = logging.getLogger(__name__)


def reset_two_factor(*, user: User, by: User) -> bool:
    """Remove every authenticator of `user` (app, security keys, recovery codes).

    For someone who lost their second factor: the password alone lets them in
    again, and staff are sent to set a new one up at once
    (`RequireStaffMFAMiddleware`). Logged with who did it, like impersonation.
    Returns False when there was nothing to remove.
    """
    deleted, _ = Authenticator.objects.filter(user=user).delete()
    if not deleted:
        return False
    logger.warning(
        "Two-factor authentication of %s (id %s) reset by %s (id %s)",
        user.get_username(),
        user.pk,
        by.get_username(),
        by.pk,
    )
    return True


@transaction.atomic
def sync_email_address(*, user: User) -> None:
    """Make allauth's record of the user's addresses match `user.email`.

    For a user created or edited outside allauth (the admin): allauth logs
    people in by the addresses it knows, so an old one left behind would keep
    working. A new address starts unverified: its owner confirms it at the
    first login, through the mail allauth sends then.
    """
    EmailAddress.objects.filter(user=user).exclude(email=user.email).delete()
    EmailAddress.objects.get_or_create(user=user, email=user.email, defaults={"primary": True})


def can_delete_own_account(user: User) -> bool:
    """Everybody but superusers: the last one must not lock the site by
    leaving. Another superuser removes them in the admin."""
    return not user.is_superuser


def delete_account(*, user: User) -> None:
    """Delete a user at their own request, with everything that cascades from
    them (addresses, authenticators, sessions). Logged."""
    email, pk = user.get_username(), user.pk
    user.delete()
    logger.warning("Account deleted at the user's request: %s (id %s)", email, pk)
