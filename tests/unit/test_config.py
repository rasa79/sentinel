"""Unit tests for the pydantic-settings config layer (D14)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinel.config import LLMSettings, Settings


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
    """A SENTINEL_-prefixed env var overrides config.yaml (provider switch via env)."""
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


def test_llm_provider_passthrough_via_dotenv(tmp_path: Path) -> None:
    """LLM_PROVIDER read from a .env file (not just os.environ) also selects the provider."""
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=openai\n", encoding="utf-8")
    settings = Settings(_env_file=str(env))
    assert settings.llm.provider == "openai"


def test_provider_invalid_value_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider field is a Literal, so an invalid value fails validation."""
    _unset(monkeypatch, "LLM_PROVIDER")
    monkeypatch.setenv("SENTINEL_LLM__PROVIDER", "not-a-provider")
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert "Input should be 'openai' or 'ollama'" in str(excinfo.value)


def test_llm_model_is_extra_forbid() -> None:
    """The nested llm model keeps extra='forbid': an unknown key is rejected as a typo guard."""
    with pytest.raises(ValidationError):
        LLMSettings(provider="ollama", bogus_field=1)


def test_root_settings_ignores_extra_keys() -> None:
    """The root settings model is extra='ignore' so unprefixed secret vars in .env are tolerated."""
    settings = Settings(bogus_field=1)
    assert settings.llm.provider == "ollama"


def test_loads_from_dotenv_with_all_example_values_including_secrets(tmp_path: Path) -> None:
    """Settings loads cleanly from a .env containing all documented example values + key secrets."""
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=openai",
                "SENTINEL_LLM__MODEL=phi4-mini",
                "SENTINEL_LLM__BASE_URL=https://api.openai.com/v1",
                "SENTINEL_LLM__API_KEY_ENV=OPENAI_API_KEY",
                "SENTINEL_LLM__TEMPERATURE=0.0",
                "SENTINEL_EMBEDDINGS__MODEL_NAME=all-MiniLM-L6-v2",
                "SENTINEL_DATABASE__URL=postgresql://sentinel:sentinel@localhost:5432/sentinel",
                "SENTINEL_LOKI__URL=http://localhost:3100",
                "SENTINEL_PROMETHEUS__URL=http://localhost:9090",
                'SENTINEL_REMEDIATION__ALLOWED_ACTIONS=["restart_service","no_action"]',
                'SENTINEL_REMEDIATION__ALLOWED_SERVICES=["orders","payments","inventory"]',
                "SENTINEL_REMEDIATION__DRY_RUN=true",
                "SENTINEL_REMEDIATION__CONFIDENCE_THRESHOLD=0.7",
                "SENTINEL_VERIFICATION__DELAY_SECONDS=30",
                "SENTINEL_VERIFICATION__ATTEMPTS=3",
                "OPENAI_API_KEY=sk-this-is-not-a-real-key",
                "DEEPSEEK_API_KEY=sk-this-is-not-a-real-deepseek-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=str(env))
    assert settings.llm.provider == "openai"  # LLM_PROVIDER passthrough honored from .env
    assert settings.llm.base_url == "https://api.openai.com/v1"
    assert settings.database.url == "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    assert settings.remediation.allowed_actions == ["restart_service", "no_action"]
    assert settings.verification.attempts == 3


def test_list_fields_round_trip_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JSON array env var replaces the yaml list wholesale."""
    monkeypatch.setenv("SENTINEL_REMEDIATION__ALLOWED_ACTIONS", '["restart_service","no_action"]')
    settings = Settings()
    assert settings.remediation.allowed_actions == ["restart_service", "no_action"]
