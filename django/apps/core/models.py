"""The only table the core app owns: the maintenance switch.

(The module must exist in any case: Django sends `pre_migrate` / `post_migrate`
only for apps that have a models module, and `apps.core.signals` relies on them.)
"""

from typing import Self

from django.db import models
from django.utils.translation import gettext_lazy as _


class MaintenanceMode(models.Model):
    """Single row (pk=1): whether the site answers 503 to everyone but staff.

    In the database, not in a file or in the per-process cache, so that every
    gunicorn worker and every container sees the same state at once.
    """

    SINGLETON_PK = 1

    enabled = models.BooleanField(
        _("maintenance mode"),
        default=False,
        help_text=_(
            "While on, visitors get a maintenance page (HTTP 503). "
            "Staff and the admin site keep working."
        ),
    )
    updated_at = models.DateTimeField(_("last change"), auto_now=True)

    class Meta:
        verbose_name = _("maintenance mode")
        verbose_name_plural = _("maintenance mode")

    def __str__(self) -> str:
        return str(_("On") if self.enabled else _("Off"))

    @classmethod
    def load(cls) -> Self:
        """The one row, created switched off the first time it is needed."""
        obj, _created = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj
