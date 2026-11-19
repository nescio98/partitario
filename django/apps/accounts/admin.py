from typing import Any

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from hijack.contrib.admin import HijackUserAdminMixin
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm
from unfold.forms import UserChangeForm as UnfoldUserChangeForm
from unfold.forms import UserCreationForm as UnfoldUserCreationForm

from . import selectors, services
from .models import User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(HijackUserAdminMixin, BaseUserAdmin, ModelAdmin):
    # HijackUserAdminMixin adds an "impersonate" button to each row of the list.
    # Unfold-styled replacements for the stock auth forms. There is no
    # username and no name: the stock fieldsets, list and ordering are
    # redeclared around the email address.
    form = UnfoldUserChangeForm
    add_form = UnfoldUserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ("email", "is_staff", "is_active", "two_factor")
    search_fields = ("email",)
    ordering = ("email",)
    actions = ["reset_two_factor"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "usable_password", "password1", "password2"),
            },
        ),
    )

    def save_model(self, request: HttpRequest, obj: User, form: Any, change: bool) -> None:
        super().save_model(request, obj, form, change)
        # allauth logs people in by the addresses it knows: keep it in step.
        services.sync_email_address(user=obj)

    def get_queryset(self, request: HttpRequest) -> QuerySet[User]:
        return selectors.with_two_factor_flag(super().get_queryset(request))

    @admin.display(boolean=True, description=_("Two-factor"))
    def two_factor(self, obj: User) -> bool:
        return bool(getattr(obj, "has_two_factor", False))

    # For a user who lost their second factor. Superusers only, and logged.
    @admin.action(
        description=_("Reset two-factor authentication"), permissions=["reset_two_factor"]
    )
    def reset_two_factor(self, request: HttpRequest, queryset: QuerySet[User]) -> None:
        if not isinstance(request.user, User):  # anonymous: never gets this far
            raise PermissionDenied
        count = sum(services.reset_two_factor(user=user, by=request.user) for user in queryset)
        self.message_user(
            request,
            ngettext(
                "Two-factor authentication reset for %(count)d user.",
                "Two-factor authentication reset for %(count)d users.",
                count,
            )
            % {"count": count},
            messages.SUCCESS if count else messages.WARNING,
        )

    def has_reset_two_factor_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
