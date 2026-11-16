"""Who may impersonate whom (settings.HIJACK_PERMISSION_CHECK)."""

from .models import User


def can_hijack(*, hijacker: User, hijacked: User | None) -> bool:
    """A superuser may act as any active user, except another superuser.

    Stricter than django-hijack's default on purpose: nobody can leave actions
    under the name of someone with the same powers.
    """
    if hijacked is None or not hijacked.is_active:
        return False
    return hijacker.is_superuser and not hijacked.is_superuser
