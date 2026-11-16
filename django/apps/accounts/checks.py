"""System checks of the accounts app, registered in `AccountsConfig.ready`."""

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import CheckMessage, Error

# Where real people sign up. dev and staging keep Cloudflare's public test
# keys, which accept everybody.
REAL_KEY_ENVIRONMENTS = {"prod", "selfhost"}


def turnstile_keys(app_configs: Sequence[AppConfig] | None, **kwargs: Any) -> list[CheckMessage]:
    """Production does not protect signup with the test keys. Run by every
    management command, `migrate` included: the stack does not start."""
    if not (settings.ACCOUNT_SIGNUP_OPEN and settings.TURNSTILE_ENABLED):
        return []
    if settings.ENV not in REAL_KEY_ENVIRONMENTS:
        return []
    # "<...": a placeholder of the env template left as it was.
    keys = (settings.TURNSTILE_SITE_KEY, settings.TURNSTILE_SECRET_KEY)
    if not any(key in settings.TURNSTILE_TEST_KEYS or key.startswith("<") for key in keys):
        return []
    return [
        Error(
            "Signup has no real Turnstile keys: Cloudflare's test keys let everybody through.",
            hint=(
                "Set TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY to the keys of this site's "
                "Turnstile widget, or close signup with DJANGO_ACCOUNT_SIGNUP_OPEN=False."
            ),
            id="accounts.E001",
        )
    ]
