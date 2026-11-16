from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django_tasks_db.admin import DBTaskResultAdmin as BaseDBTaskResultAdmin
from django_tasks_db.models import DBTaskResult
from unfold.admin import ModelAdmin

from .models import MaintenanceMode


@admin.register(MaintenanceMode)
class MaintenanceModeAdmin(ModelAdmin):
    """One row to switch: it can be neither added twice nor deleted."""

    list_display = ["__str__", "updated_at"]
    readonly_fields = ["updated_at"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[MaintenanceMode]:
        MaintenanceMode.load()  # make sure the row is there to be edited
        return super().get_queryset(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: MaintenanceMode | None = None
    ) -> bool:
        return False


admin.site.unregister(DBTaskResult)


@admin.register(DBTaskResult)
class DBTaskResultAdmin(BaseDBTaskResultAdmin, ModelAdmin):
    """Background tasks, read-only: what ran, what failed and why.

    Superusers only: the arguments of a task are shown, and those of a queued
    mail are the mail itself (a password reset link, for one).
    """

    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser

    def has_view_permission(self, request: HttpRequest, obj: DBTaskResult | None = None) -> bool:
        return request.user.is_superuser
