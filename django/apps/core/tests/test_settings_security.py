"""Settings are evaluated at import time, so each case runs in a fresh process."""

import json
import os
import subprocess
import sys

from django.conf import settings

FLAGS = [
    "SECURE_SSL_REDIRECT",
    "SECURE_HSTS_SECONDS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SESSION_COOKIE_NAME",
    "CSRF_COOKIE_NAME",
    "SECURE_PROXY_SSL_HEADER",
    "ALLAUTH_TRUSTED_PROXY_COUNT",
]
PROBE = (
    "import json, django; django.setup(); from django.conf import settings as s; "
    f"print(json.dumps({{n: getattr(s, n, None) for n in {FLAGS!r}}}))"
)


def run(*args: str, debug: bool, dev_port: str = "") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_DEBUG": str(debug),
        # Set even when empty, so that the value of the developer's .env stays out.
        "DJANGO_DEV_PORT": dev_port,
        "DJANGO_SECRET_KEY": "test-only-" + "x" * 60,
        # A real mail server is part of a deployable configuration.
        "EMAIL_HOST": "smtp.example.com",
    }
    # Only DEBUG decides: no flag may leak in from the developer's environment.
    for name in (
        "DJANGO_SECURE_SSL_REDIRECT",
        "DJANGO_SECURE_HSTS_SECONDS",
        "DJANGO_SECURE_PROXY_SSL_HEADER",
        "DJANGO_SESSION_COOKIE_SECURE",
        "DJANGO_CSRF_COOKIE_SECURE",
    ):
        env.pop(name, None)
    return subprocess.run(
        [sys.executable, *args], cwd=settings.BASE_DIR, env=env, capture_output=True, text=True
    )


def flags(debug: bool, dev_port: str = "") -> dict:
    result = run("-c", PROBE, debug=debug, dev_port=dev_port)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_debug_off_is_secure_by_default():
    assert flags(debug=False) == {
        "SECURE_SSL_REDIRECT": True,
        "SECURE_HSTS_SECONDS": 3600,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        "SESSION_COOKIE_NAME": "__Host-sessionid",
        "CSRF_COOKIE_NAME": "__Host-csrftoken",
        "SECURE_PROXY_SSL_HEADER": ["HTTP_X_FORWARDED_PROTO", "https"],
        # Behind nginx: its single X-Forwarded-For hop is the client address.
        "ALLAUTH_TRUSTED_PROXY_COUNT": 1,
    }


def test_debug_on_works_over_plain_http():
    result = flags(debug=True)
    assert result["SECURE_SSL_REDIRECT"] is False
    assert result["SECURE_HSTS_SECONDS"] == 0
    assert result["SESSION_COOKIE_SECURE"] is False
    assert result["SESSION_COOKIE_NAME"] == "sessionid"
    assert result["SECURE_PROXY_SSL_HEADER"] is None
    assert result["ALLAUTH_TRUSTED_PROXY_COUNT"] == 0


def test_dev_port_keeps_the_cookies_of_parallel_dev_servers_apart():
    result = flags(debug=True, dev_port="8008")
    assert result["SESSION_COOKIE_NAME"] == "sessionid_8008"
    assert result["CSRF_COOKIE_NAME"] == "csrftoken_8008"


def test_dev_port_changes_nothing_outside_debug():
    result = flags(debug=False, dev_port="8008")
    assert result["SESSION_COOKIE_NAME"] == "__Host-sessionid"
    assert result["CSRF_COOKIE_NAME"] == "__Host-csrftoken"


def test_deploy_check_is_clean():
    result = run("manage.py", "check", "--deploy", "--fail-level", "WARNING", debug=False)
    assert result.returncode == 0, result.stdout + result.stderr
