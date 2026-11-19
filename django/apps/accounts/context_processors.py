from typing import Any

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest

from .middleware import is_account_view


def account_pages(request: HttpRequest) -> dict[str, Any]:
    """Give the allauth pages what the admin gives its own templates (site
    title, colours, stylesheets), so `templates/allauth/layouts/base.html` can
    build on Unfold's layout, plus whether to invite people to sign up. Empty
    for every other page."""
    match = request.resolver_match
    if match is None or not is_account_view(match.func):
        return {}
    return {**admin.site.each_context(request), "signup_open": settings.ACCOUNT_SIGNUP_OPEN}
