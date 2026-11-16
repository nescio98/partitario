"""The pages allauth does not provide: where a login lands, and the account
page that ties allauth's own pages (address, password, two-factor
authentication, sessions) together."""

from allauth.account.decorators import reauthentication_required
from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from . import services
from .models import User


def home(request: HttpRequest) -> HttpResponse:
    """`/`, and where a login lands: the admin for staff, the account page for
    everybody else. A project with pages of its own replaces this."""
    if request.user.is_staff:
        return redirect("admin:index")
    return redirect("account_manage")


@login_required
def manage(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not isinstance(user, User):  # anonymous: login_required never lets it this far
        raise PermissionDenied
    email_verified = EmailAddress.objects.filter(
        user=user, email=user.email, verified=True
    ).exists()
    return render(
        request,
        "account/manage.html",
        {
            "email_verified": email_verified,
            "can_delete": services.can_delete_own_account(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def delete(request: HttpRequest) -> HttpResponse:
    user = request.user
    # While impersonating, the account is somebody else's.
    if (
        not isinstance(user, User)
        or getattr(user, "is_hijacked", False)
        or not services.can_delete_own_account(user)
    ):
        raise PermissionDenied
    return _confirm_delete(request, user)


# Asks for the password again first (allauth), like every change to the account.
@reauthentication_required(allow_get=True)
def _confirm_delete(request: HttpRequest, user: User) -> HttpResponse:
    if request.method == "POST":
        logout(request)
        services.delete_account(user=user)
        messages.success(request, _("Your account was deleted."))
        return redirect("account_login")
    return render(request, "account/delete.html")
