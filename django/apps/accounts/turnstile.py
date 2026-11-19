"""Cloudflare Turnstile: the form field that keeps bots out of signup.

The widget is Cloudflare's script, which adds a token to the form once it is
satisfied that a person is there (usually without asking anything); the field
has Cloudflare confirm that token, from the server. No package needed: it is
one div and one POST.

https://developers.cloudflare.com/turnstile/
"""

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms.renderers import BaseRenderer
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# The name Cloudflare's script gives the hidden input it adds to the form.
RESPONSE_FIELD = "cf-turnstile-response"


def verify(token: str) -> bool:
    """Ask Cloudflare whether `token` came from a visitor it let through.

    A token is good once, for five minutes. If Cloudflare cannot be reached
    the answer is no: an outage must not open signup to everybody.
    """
    data = urllib.parse.urlencode(
        {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    ).encode()
    try:
        # A constant https URL: nothing a visitor typed decides where this goes.
        with urllib.request.urlopen(VERIFY_URL, data=data, timeout=5) as response:
            result = json.load(response)
    except (OSError, ValueError):
        logger.exception("Turnstile could not be reached")
        return False
    if result.get("success") is True:
        return True
    logger.warning("Turnstile refused a token: %s", result.get("error-codes"))
    return False


class TurnstileWidget(forms.Widget):
    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        return data.get(RESPONSE_FIELD)

    def render(
        self,
        name: str,
        value: Any,
        attrs: dict[str, Any] | None = None,
        renderer: BaseRenderer | None = None,
    ) -> SafeString:
        return format_html(
            '<div class="cf-turnstile" data-sitekey="{}" data-language="{}"></div>'
            '<script src="{}" async defer></script>',
            settings.TURNSTILE_SITE_KEY,
            get_language() or "auto",
            SCRIPT_URL,
        )


class TurnstileField(forms.Field):
    widget = TurnstileWidget
    default_error_messages = {
        "required": _("Confirm that you are not a robot."),
        "invalid": _("The verification failed. Try again."),
    }

    def validate(self, value: Any) -> None:
        super().validate(value)
        if not verify(value):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
