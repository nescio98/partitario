"""State backend of django-maintenance-mode, kept in the database."""

import logging

from django.db import Error as DatabaseError
from maintenance_mode.backends import AbstractStateBackend

logger = logging.getLogger(__name__)


class DatabaseStateBackend(AbstractStateBackend):
    """Reads `MaintenanceMode` on every request: one primary-key lookup.

    The default backend writes a file, which a read-only container cannot do
    and which other containers would not see. If the database cannot answer,
    maintenance counts as off: a broken lookup must not lock the site.
    """

    def get_value(self) -> bool:
        from .models import MaintenanceMode

        try:
            enabled = (
                MaintenanceMode.objects.filter(pk=MaintenanceMode.SINGLETON_PK)
                .values_list("enabled", flat=True)
                .first()
            )
        except DatabaseError:
            logger.warning("Maintenance mode lookup failed, assuming off", exc_info=True)
            return False
        return bool(enabled)

    def set_value(self, value: bool) -> None:
        from .models import MaintenanceMode

        MaintenanceMode.objects.update_or_create(
            pk=MaintenanceMode.SINGLETON_PK, defaults={"enabled": bool(value)}
        )
