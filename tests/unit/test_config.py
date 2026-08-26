"""Unit tests for the pydantic-settings config layer (D14)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from sentinel.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no SENTINEL_* / LLM_PROVIDER vars leak between tests."""
    for key in list(os.environ):
        if key.startswith("SENTINEL_") or key == "LLM_PROVIDER":
            monkeypatch.delenv(key, raising=False)


def _unset(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.delenv(key, raising=False)


def test_defaults_load_from_config_yaml() -> None:
    """Base config.yaml should provide the defaults when no env vars are set."""
    settings = Settings()
    assert settings.llm.provider == "ollama"
    assert settings.llm.model == "phi4-mini"  # machine-local model via config.yaml
    assert settings.embeddings.model_name == "all-MiniLM-L6-v2"
    assert settings.verification.attempts == 3
    assert settings.remediation.dry_run is True


def test_env_var_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    _unset(monkeypatch, "LLM_PROVIDER")
    monkeypatch.setenv("SENTINEL_LLM__PROVIDER", "openai")
    monkeypatch.setenv("SENTINEL_DATABASE__URL", "postgresql://u:p@db:5432/x")
    settings = Settings()
    assert settings.llm.provider == "openai"
    assert settings.database.url == "postgresql://u:p@db:5432/x"


def test_llm_provider_passthrough_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_PROVIDER (no prefix) is a convenience switch that always wins over yaml/env."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("SENTINEL_LLM__PROVIDER", "ollama")  # explicit env set too
    settings = Settings()
    assert settings.llm.provider == "openai"


def test_provider_invalid_value_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _unset(monkeypatch, "LLM_PROVIDER")
    monkeypatch.setenv("SENTINEL_LLM__PROVIDER", "not-a-provider")
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert "must be 'ollama' or 'openai'" in str(excinfo.value)


def test_extra_key_rejected() -> None:
    """extra='forbid' rejects keys that are not declared on the model (a typo guard).

    Note: pydantic-settings does NOT raise for an unknown ``SENTINEL_*`` env var (it just
    ignores it), so the guard shows up on data the model sees directly (init/YAML), which
    is the path that catches config.yaml drift.
    """
    with pytest.raises(ValidationError):
        Settings(bogus_field=1)


def test_list_fields_round_trip_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JSON array env var replaces the yaml list wholesale."""
    monkeypatch.setenv("SENTINEL_REMEDIATION__ALLOWED_ACTIONS", '["restart_service","no_action"]')
    settings = Settings()
    assert settings.remediation.allowed_actions == ["restart_service", "no_action"]
