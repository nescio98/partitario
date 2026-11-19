"""Typed access to environment variables, for `config.settings`.

One place decides how a value is parsed and how a bad one is reported: a
missing or malformed variable fails startup with `ImproperlyConfigured`, naming
the variable. A variable set to the empty string counts as not set.
"""

import os

from django.core.exceptions import ImproperlyConfigured

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _building() -> bool:
    """Image build (`DJANGO_BUILD=1`): collectstatic and compilemessages load the
    settings without any runtime configuration, so nothing is required."""
    return os.getenv("DJANGO_BUILD") == "1"


def env_str(name: str, default: str | None = None) -> str:
    """The variable as a string. Without a default it is required."""
    value = os.getenv(name, "")
    if value:
        return value
    if default is not None:
        return default
    if _building():
        return ""
    raise ImproperlyConfigured(f"Missing required environment variable: {name} (see .env.example)")


def env_bool(name: str, default: bool) -> bool:
    """true/false, yes/no, on/off, 1/0 (any case). Anything else is an error, so
    a typo can never silently switch a security flag off."""
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} must be true or false, not {os.environ[name]!r}")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer, not {value!r}") from None


def env_list(name: str, default: str | None = "") -> list[str]:
    """Whitespace-separated values. `default=None` makes the variable required."""
    return env_str(name, default).split()
