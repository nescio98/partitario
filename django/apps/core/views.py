"""Infrastructure views: private delivery of uploaded documents."""

from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseBase
from django.views.decorators.http import require_safe

# Internal nginx location mapped onto MEDIA_ROOT (docker/nginx/default.conf.template).
ACCEL_PREFIX = "/_protected_media/"


@require_safe
@login_required
def protected_media(request: HttpRequest, path: str) -> HttpResponseBase:
    """Serve an uploaded document to a logged-in user (STORAGE_BACKEND=filesystem).

    There is no public media URL: this view is the only way to a file. Behind
    nginx it only authorises the request and lets nginx send the file.
    """
    if settings.STORAGE_BACKEND != "filesystem":
        raise Http404
    try:
        # The storage resolves the name and refuses anything outside MEDIA_ROOT.
        file_path = Path(default_storage.path(path))
    except SuspiciousFileOperation:
        raise Http404 from None
    if not file_path.is_file():
        raise Http404

    response: HttpResponseBase
    if settings.MEDIA_ACCEL_REDIRECT:
        response = HttpResponse()
        response["X-Accel-Redirect"] = ACCEL_PREFIX + quote(path)
        # Let nginx pick the content type from the file name.
        del response["Content-Type"]
    else:
        response = FileResponse(file_path.open("rb"))
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["Cache-Control"] = "private, no-store"
    return response
