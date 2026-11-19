from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.http import HttpRequest


class AccountAdapter(DefaultAccountAdapter):
    """Signup is open unless the project closes it (settings.ACCOUNT_SIGNUP_OPEN):
    then users are only created in the admin."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return settings.ACCOUNT_SIGNUP_OPEN
