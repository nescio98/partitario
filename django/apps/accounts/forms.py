"""Forms of the account pages."""

from typing import Any

from allauth.account.forms import SignupForm as AllauthSignupForm
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .turnstile import TurnstileField


class SignupForm(AllauthSignupForm):
    """allauth's signup form (settings.ACCOUNT_FORMS) behind Cloudflare
    Turnstile, unless settings.TURNSTILE_ENABLED is off."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if settings.TURNSTILE_ENABLED:
            self.fields["turnstile"] = TurnstileField(label=_("Verification"))
