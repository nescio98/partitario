import uuid
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra_fields: Any) -> "User":
        if not email:
            raise ValueError("A user needs an email address")
        user = self.model(email=email.strip().lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> "User":
        """The user of `createsuperuser` / `ensure_superuser`.

        Their address counts as verified: whoever runs this has a shell on the
        server, and the first administrator must get in before any mail works.
        """
        from allauth.account.models import EmailAddress

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not (extra_fields["is_staff"] and extra_fields["is_superuser"]):
            raise ValueError("A superuser has is_staff=True and is_superuser=True")
        user = self._create(email, password, **extra_fields)
        EmailAddress.objects.using(self._db).create(
            user=user, email=user.email, primary=True, verified=True
        )
        return user

    def get_by_natural_key(self, email: str | None) -> "User":
        """Addresses are stored lowercase: look them up the same way, so
        `authenticate()` accepts any casing."""
        return super().get_by_natural_key(email.lower() if email else email)


class User(AbstractBaseUser, PermissionsMixin):
    """Project user model: an email address and a password, keyed by a UUID.

    Built on Django's bare user rather than `AbstractUser`: there is no
    username and no name. People log in with their address (django-allauth,
    which also keeps track of whether it was verified). The primary key is a
    random UUID, so it can appear in a URL or a log without revealing how many
    users there are, or which one comes next.

    Addresses are always lowercase, so they are unique whatever their casing:
    the manager and `clean()` (every model form) lower them, and a database
    constraint refuses anything that slipped past.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(
        _("email address"),
        unique=True,
        error_messages={"unique": _("A user with this email address already exists.")},
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="accounts_user_email_lowercase",
                violation_error_message=_("The email address must be lowercase."),
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.email = self.email.strip().lower()
