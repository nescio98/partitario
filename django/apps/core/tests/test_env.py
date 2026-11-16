"""config.env: how environment variables are parsed and rejected."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_list, env_str


@pytest.fixture(autouse=True)
def _not_building(monkeypatch):
    monkeypatch.delenv("DJANGO_BUILD", raising=False)


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "on", " true "])
def test_bool_true_spellings(monkeypatch, value):
    monkeypatch.setenv("FLAG", value)
    assert env_bool("FLAG", default=False) is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_bool_false_spellings(monkeypatch, value):
    monkeypatch.setenv("FLAG", value)
    assert env_bool("FLAG", default=True) is False


@pytest.mark.parametrize("default", [True, False])
def test_bool_unset_or_empty_is_the_default(monkeypatch, default):
    monkeypatch.delenv("FLAG", raising=False)
    assert env_bool("FLAG", default=default) is default
    monkeypatch.setenv("FLAG", "")
    assert env_bool("FLAG", default=default) is default


def test_bool_typo_is_an_error_not_false(monkeypatch):
    monkeypatch.setenv("FLAG", "ture")
    with pytest.raises(ImproperlyConfigured, match="FLAG must be true or false"):
        env_bool("FLAG", default=True)


def test_str_required_and_default(monkeypatch):
    monkeypatch.delenv("NAME", raising=False)
    with pytest.raises(ImproperlyConfigured, match="NAME"):
        env_str("NAME")
    assert env_str("NAME", "fallback") == "fallback"
    monkeypatch.setenv("NAME", "value")
    assert env_str("NAME", "fallback") == "value"


def test_required_values_are_not_needed_during_the_image_build(monkeypatch):
    monkeypatch.delenv("NAME", raising=False)
    monkeypatch.setenv("DJANGO_BUILD", "1")
    assert env_str("NAME") == ""
    assert env_list("NAME", default=None) == []


def test_int(monkeypatch):
    monkeypatch.delenv("NUMBER", raising=False)
    assert env_int("NUMBER", 7) == 7
    monkeypatch.setenv("NUMBER", "42")
    assert env_int("NUMBER", 7) == 42
    monkeypatch.setenv("NUMBER", "forty-two")
    with pytest.raises(ImproperlyConfigured, match="NUMBER must be an integer"):
        env_int("NUMBER", 7)


def test_list(monkeypatch):
    monkeypatch.setenv("HOSTS", "a.example.com  b.example.com")
    assert env_list("HOSTS") == ["a.example.com", "b.example.com"]
    monkeypatch.delenv("HOSTS")
    assert env_list("HOSTS") == []
    with pytest.raises(ImproperlyConfigured, match="HOSTS"):
        env_list("HOSTS", default=None)
