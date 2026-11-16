"""Static files storage of the hosted stacks."""

import logging

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage

logger = logging.getLogger(__name__)


class LenientManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """Content-hashed static URLs that never turn a missing file into a 500.

    `{% static "x.css" %}` for a file that is not in the manifest raises
    `ValueError` with Django's storage, and since DEBUG uses the plain storage
    the mistake only shows in production. Here the unhashed name is served
    instead (a 404 for that one file) and a warning is logged.

    Only this lookup is lenient: `collectstatic` still fails on a broken
    `url(...)` inside a stylesheet, so the image build stays strict.
    """

    def stored_name(self, name: str) -> str:
        try:
            return super().stored_name(name)
        except ValueError:
            logger.warning("Static file %r is not in the manifest: serving its unhashed name", name)
            return name
