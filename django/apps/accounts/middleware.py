"""Two-factor authentication is mandatory for staff (settings.STAFF_MFA_REQUIRED)."""

from collections.abc import Callable
from typing import Any

from allauth.mfa.utils import is_mfa_enabled
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _


def is_account_view(view_func: Callable[..., Any]) -> bool:
    """The account pages: allauth's (login, logout, password, two-factor
    setup) and the two of apps/accounts/views.py around them."""
    return view_func.__module__.startswith(("allauth.", "apps.accounts.views"))


class RequireStaffMFAMiddleware:
    """Send staff who have no second factor to its setup, whatever they ask for.

    allauth offers two-factor authentication but never demands it. The account
    pages stay reachable (to set it up, or to log out). While impersonating,
    the superuser's own second factor counts, not the impersonated user's.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable[..., Any],
        view_args: tuple[Any, ...],
        view_kwargs: dict[str, Any],
    ) -> HttpResponse | None:
        if not settings.STAFF_MFA_REQUIRED:
            return None
        user = request.user
        if not (user.is_authenticated and user.is_staff):
            return None
        if getattr(user, "is_hijacked", False) or is_account_view(view_func):
            return None
        if is_mfa_enabled(user):
            return None
        messages.warning(
            request, _("Set up two-factor authentication to continue: it is required.")
        )
        return redirect("mfa_index")
