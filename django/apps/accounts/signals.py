"""Audit trail of who gets in, and as whom, connected in `AccountsConfig.ready`.

Logins (successful and failed), logouts, changes to the second factor and
impersonations (django-hijack). Everything goes to the log, like the rest.
"""

import logging
from typing import Any

from allauth.account.adapter import get_adapter
from allauth.mfa.models import Authenticator
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .models import User

logger = logging.getLogger(__name__)


def _client_ip(request: HttpRequest | None) -> str:
    """The address allauth counts its rate limits on (ALLAUTH_TRUSTED_PROXY_COUNT)."""
    if request is None:
        return "unknown address"
    try:
        return get_adapter().get_client_ip(request)
    except PermissionDenied:
        return "unknown address"


def log_login(sender: object, request: HttpRequest | None, user: User, **kwargs: object) -> None:
    logger.info("Login: %s (id %s) from %s", user.get_username(), user.pk, _client_ip(request))


def log_logout(
    sender: object, request: HttpRequest | None, user: User | None, **kwargs: object
) -> None:
    if user is not None:
        logger.info("Logout: %s (id %s)", user.get_username(), user.pk)


def log_login_failed(
    sender: object,
    credentials: dict[str, Any],
    request: HttpRequest | None = None,
    **kwargs: object,
) -> None:
    # %r: the address is whatever a stranger typed, keep it on one line.
    logger.warning("Login failed for %r from %s", credentials.get("email"), _client_ip(request))


def log_mfa_failed(sender: object, request: HttpRequest, user: User, **kwargs: object) -> None:
    logger.warning(
        "Two-factor code rejected for %s (id %s) from %s",
        user.get_username(),
        user.pk,
        _client_ip(request),
    )


def log_authenticator_added(
    sender: object, request: HttpRequest, user: User, authenticator: Authenticator, **kwargs: object
) -> None:
    logger.warning(
        "Two-factor authentication: %s (id %s) added %s",
        user.get_username(),
        user.pk,
        authenticator.type,
    )


def log_authenticator_removed(
    sender: object, request: HttpRequest, user: User, authenticator: Authenticator, **kwargs: object
) -> None:
    logger.warning(
        "Two-factor authentication: %s (id %s) removed %s",
        user.get_username(),
        user.pk,
        authenticator.type,
    )


def log_hijack_started(
    sender: object, hijacker: User, hijacked: User, request: HttpRequest, **kwargs: object
) -> None:
    logger.warning(
        "Impersonation started: %s (id %s) is acting as %s (id %s)",
        hijacker.get_username(),
        hijacker.pk,
        hijacked.get_username(),
        hijacked.pk,
    )


def log_hijack_ended(
    sender: object, hijacker: User, hijacked: User, request: HttpRequest, **kwargs: object
) -> None:
    logger.warning(
        "Impersonation ended: %s (id %s) stopped acting as %s (id %s)",
        hijacker.get_username(),
        hijacker.pk,
        hijacked.get_username(),
        hijacked.pk,
    )
