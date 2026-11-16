"""Reads on accounts."""

from allauth.mfa.models import Authenticator
from django.db.models import Exists, OuterRef, QuerySet

from .models import User


def with_two_factor_flag(users: QuerySet[User]) -> QuerySet[User]:
    """Annotate each user with `has_two_factor`: do they have a second factor?"""
    return users.annotate(has_two_factor=Exists(Authenticator.objects.filter(user=OuterRef("pk"))))
