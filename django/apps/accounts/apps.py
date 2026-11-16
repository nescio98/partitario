from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = _("Account")

    def ready(self) -> None:
        from allauth.mfa import signals as mfa_signals
        from django.contrib.auth import signals as auth_signals
        from django.core import checks as django_checks
        from hijack.signals import hijack_ended, hijack_started

        from . import checks, signals

        django_checks.register(checks.turnstile_keys)

        auth_signals.user_logged_in.connect(signals.log_login)
        auth_signals.user_logged_out.connect(signals.log_logout)
        auth_signals.user_login_failed.connect(signals.log_login_failed)
        mfa_signals.authentication_failed.connect(signals.log_mfa_failed)
        mfa_signals.authenticator_added.connect(signals.log_authenticator_added)
        mfa_signals.authenticator_removed.connect(signals.log_authenticator_removed)
        hijack_started.connect(signals.log_hijack_started)
        hijack_ended.connect(signals.log_hijack_ended)
