"""Tests for ``ontozense.cli._load_env`` — Azure env var aliasing.

Tycho 1.0+ alias map: when a user has the standard Azure SDK env var
naming convention (``AZURE_OPENAI_*``), ``_load_env`` copies the
values to LiteLLM's expected names (``AZURE_*``) so OntoGPT can find
the credentials without the user duplicating entries in their ``.env``.

Surfaced during the round-5 ESG validation run.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Clear both naming conventions AND stub out ``dotenv.load_dotenv``
    so the repo's real ``.env`` doesn't repopulate Azure values back
    into ``os.environ`` mid-test (``load_dotenv`` searches upward from
    cwd by default, so chdir doesn't help)."""
    for key in (
        "AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION",
        "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
    ):
        monkeypatch.delenv(key, raising=False)
    # Stub at the import path _load_env() uses inside its function body
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)


def test_alias_copies_from_azure_openai_to_azure_api(monkeypatch, clean_env):
    """The Azure SDK names (``AZURE_OPENAI_*``) propagate to LiteLLM's
    names (``AZURE_*``) when the LiteLLM names are unset."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key-from-azure-sdk")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    from ontozense.cli import _load_env
    _load_env()

    assert os.environ["AZURE_API_KEY"] == "fake-key-from-azure-sdk"
    assert os.environ["AZURE_API_BASE"] == "https://example.openai.azure.com/"
    assert os.environ["AZURE_API_VERSION"] == "2024-02-15-preview"


def test_existing_litellm_names_are_not_clobbered(monkeypatch, clean_env):
    """When both conventions are set, the explicit LiteLLM names win.
    This is the user's escape hatch: if they want to point Tycho at a
    different endpoint than their Azure SDK default, setting
    ``AZURE_API_BASE`` should take precedence."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "sdk-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://sdk.example.com/")
    monkeypatch.setenv("AZURE_API_KEY", "explicit-litellm-key")
    monkeypatch.setenv("AZURE_API_BASE", "https://explicit.example.com/")

    from ontozense.cli import _load_env
    _load_env()

    # Explicit names are preserved verbatim
    assert os.environ["AZURE_API_KEY"] == "explicit-litellm-key"
    assert os.environ["AZURE_API_BASE"] == "https://explicit.example.com/"


def test_no_azure_env_vars_set_is_noop(monkeypatch, clean_env):
    """When neither convention is set, _load_env runs silently and
    doesn't fabricate any keys. Useful baseline so a misconfigured
    env doesn't silently inject empty strings into LiteLLM calls."""
    from ontozense.cli import _load_env
    _load_env()

    assert "AZURE_API_KEY" not in os.environ
    assert "AZURE_API_BASE" not in os.environ
    assert "AZURE_API_VERSION" not in os.environ


def test_partial_azure_openai_aliases_what_is_present(monkeypatch, clean_env):
    """If only one of the SDK vars is set (e.g. user set KEY but not
    ENDPOINT), only that one is aliased — others stay unset."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "only-key")

    from ontozense.cli import _load_env
    _load_env()

    assert os.environ["AZURE_API_KEY"] == "only-key"
    assert "AZURE_API_BASE" not in os.environ
    assert "AZURE_API_VERSION" not in os.environ
