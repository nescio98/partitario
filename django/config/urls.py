from allauth.account.decorators import secure_admin_login
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import home

# One login for everybody: the admin's own form is replaced by a redirect to
# allauth's, so its rate limits and two-factor authentication cannot be skipped.
admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    # Ours first: the account page and account deletion, around allauth's pages.
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("hijack/", include("hijack.urls")),
    path("", include("apps.core.urls")),
]
