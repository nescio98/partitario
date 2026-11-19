from collections.abc import Callable

from django.db import Error as DatabaseError
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase

PLAIN = "text/plain"


class HealthCheckMiddleware:
    """Answer the container healthchecks before any other middleware runs.

    /healthz  the process is up (liveness)
    /readyz   the database answers too (readiness; the compose healthcheck)

    Sitting first in MIDDLEWARE keeps both independent of ALLOWED_HOSTS and of
    the HTTPS redirect. nginx does not expose them to the outside.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if request.path == "/healthz":
            return HttpResponse("ok", content_type=PLAIN)
        if request.path == "/readyz":
            return self.readiness()
        return self.get_response(request)

    @staticmethod
    def readiness() -> HttpResponse:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            return HttpResponse("database unavailable", status=503, content_type=PLAIN)
        return HttpResponse("ok", content_type=PLAIN)
