import os
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Create the superuser described by DJANGO_SUPERUSER_EMAIL / _PASSWORD if "
        "it does not exist yet. Idempotent: never touches an existing user."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip().lower()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        if not email or not password:
            raise CommandError("Set DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD in .env")

        user_model = get_user_model()
        if user_model.objects.filter(email=email).exists():
            self.stdout.write(f"Superuser '{email}' already exists — left untouched.")
            return

        user_model.objects.create_superuser(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser '{email}' created."))
