"""Strings of django-hijack, which ships no Italian catalogue.

Declared here only so that `make messages` keeps them in our own
`locale/*/django.po`, whose translations take precedence. Keep them identical
to the originals (hijack and unfold.contrib.hijack templates).
"""

from django.utils.translation import gettext_noop, pgettext_lazy

HIJACK_MESSAGES = (
    gettext_noop("You are currently working on behalf of <em>%(user)s</em>."),
    gettext_noop("stop impersonating"),
    gettext_noop("hide warning"),
    gettext_noop("impersonate %(username)s"),
    pgettext_lazy("verb", "impersonate"),
)
