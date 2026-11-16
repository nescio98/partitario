from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.core import diagnostics


class Command(BaseCommand):
    help = (
        "Smoke-test the backing services: PostgreSQL (schema, RLS on every "
        "Django table), the shared cache and the document storage (write/read/delete round "
        "trip; for S3, that the bucket refuses unsigned requests). Works on "
        "any Postgres, any S3-compatible store or a local directory; adds one "
        "check when the store is Supabase."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        checks = (
            diagnostics.check_database,
            diagnostics.check_rls,
            diagnostics.check_cache,
            diagnostics.check_storage,
        )
        problems: list[str] = []
        for check in checks:
            result = check()
            self.stdout.write(result.summary)
            problems.extend(result.problems)

        if problems:
            raise CommandError("Service check failed:\n- " + "\n- ".join(problems))
        self.stdout.write(self.style.SUCCESS("Backing services OK."))
