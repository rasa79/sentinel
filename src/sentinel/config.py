# LEARN[03]: configuration layering with pydantic-settings (for a Spring engineer)
# Why this way: one typed Settings object reads a base config.yaml and lets environment
#   variables override individual keys, so switching between providers or pointing at a
#   different database requires no code change — only config/state. This mirrors Spring Boot's
#   application.yml + @ConfigurationProperties + relaxed binding, but with a Rust-validated
#   Pydantic model instead of reflection.
# Good sides:
#   - every field is typed and validated once (an invalid temperature fails fast at import)
#   - a single precedence chain (defaults < config.yaml < env) is easy to reason about and
#     documented; no scattered os.getenv calls anywhere in the codebase
#   - immutable, frozen-like access: consumers get a settings object, never a dict of strings
# Drawbacks:
#   - pydantic-settings precedence can surprise people (env beats .env beats yaml), so a
#     value mysteriously wrong is usually an env var you forgot
#   - nested models need explicit config (env_nested_delimiter, custom source wiring) which
#     looks more ceremonial than application.yml
#   - secrets in env vars aren't encrypted; .env.example must never contain real values
# Concept: Spring resolves config from many sources with a defined priority (command line >
#   env > application-<profile>.yml > application.yml > defaults). pydantic-settings is the
#   twelve-factor equivalent: it layers sources in priority order — constructor args, then
#   actual environment variables (SENTINEL_*), then the .env dotenv file, then secrets, then
#   the YAML file (which we add explicitly as the lowest file source), then the model defaults.
#   This is the "config as code + config as environment" split: the checked-in config.yaml is
#   the safe baseline (no secrets, sane demo defaults), while credentials and environment
#   overrides arrive via SENTINEL_* env vars. Nested namespaces use `__` as the delimiter
#   (e.g. SENTINEL_DATABASE__URL) so a dot-separated YAML tree maps onto env vars, and a
#   leading SENTINEL_ prefix keeps our vars out of collision with unrelated daemons. The root
#   model is extra='ignore' so genuinely unprefixed secret vars (OPENAI_API_KEY / DEEPSEEK_API_KEY)
#   may sit in .env without tripping validation, while the nested llm model is extra='forbid' so a
#   typo inside that sub-model's keys is still rejected rather than silently dropped. A convenience
#   passthrough LLM_PROVIDER=ollama|openai is preprocessed onto llm.provider, so the smoke test and
#   demo scripts can flip the provider without touching config.yaml.
# See also: LEARN[01] (packaging/sync), the D14 design decision in PLAN.md
from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class LLMSettings(BaseModel):
    """LLM client settings (D3). `model` defaults to the machine's local model (phi4-mini)."""

    model_config = SettingsConfigDict(extra="forbid")

    provider: Literal["openai", "ollama"] = "ollama"
    model: str = "phi4-mini"
    base_url: str = "http://localhost:11434/v1"
    # Name (not value) of the env var holding the cloud API key; read by the provider factory.
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0


class EmbeddingsSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    model_name: str = "all-MiniLM-L6-v2"  # 384-dim, fixed by D2


class DatabaseSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    url: str = "postgresql://sentinel:sentinel@localhost:5432/sentinel"


class LokiSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    url: str = "http://localhost:3100"


class PrometheusSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    url: str = "http://localhost:9090"


class RemediationSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    allowed_actions: list[str] = Field(
        default_factory=lambda: [
            "restart_service",
            "rollback_deploy",
            "scale_replicas",
            "no_action",
        ]
    )
    allowed_services: list[str] = Field(default_factory=lambda: ["orders", "payments", "inventory"])
    dry_run: bool = True  # D11: safe by default
    confidence_threshold: float = 0.7


class VerificationSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    delay_seconds: int = 30
    attempts: int = 3


class RAGSettings(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    top_k: int = 3
    min_score: float = 0.3  # cosine similarity floor below which a result is dropped as noise


class Settings(BaseSettings):
    """Top-level typed settings object (D14).

    Precedence (highest → lowest): constructor args > SENTINEL_* env vars > `.env` file >
    secret files > `config.yaml` > model defaults. The root model is ``extra="ignore"`` so that
    unprefixed secret vars (e.g. OPENAI_API_KEY) may live in `.env` without tripping validation;
    the nested ``llm`` model stays ``extra="forbid"``. ``LLM_PROVIDER`` is a convenience
    passthrough preprocessed onto ``llm.provider`` (always wins).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SENTINEL_",
        env_nested_delimiter="__",
        yaml_file="config.yaml",
        extra="ignore",
    )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    loki: LokiSettings = Field(default_factory=LokiSettings)
    prometheus: PrometheusSettings = Field(default_factory=PrometheusSettings)
    remediation: RemediationSettings = Field(default_factory=RemediationSettings)
    verification: VerificationSettings = Field(default_factory=VerificationSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)

    @model_validator(mode="before")
    @classmethod
    def _apply_llm_provider_passthrough(cls, data: Any) -> Any:
        # LLM_PROVIDER carries no SENTINEL_ prefix. pydantic-settings' EnvSettingsSource filters
        # unprefixed vars out of `data`, but the DotEnvSettingsSource surfaces them as a flat
        # lower-cased key `llm_provider`. So resolve the passthrough from os.environ (higher
        # precedence) first, then from the dotenv data key. The model_validator runs after all
        # sources merge but before field validation, so the passthrough always wins.
        if not isinstance(data, dict):
            return data
        passthrough = os.environ.get("LLM_PROVIDER")
        dotenv_key = data.pop("llm_provider", None)
        if passthrough is None:
            passthrough = dotenv_key
        if passthrough is None:
            return data
        llm = data.get("llm")
        if isinstance(llm, dict):
            llm["provider"] = passthrough
        elif isinstance(llm, LLMSettings):
            llm.provider = passthrough  # type: ignore[assignment]
        else:
            data["llm"] = {"provider": passthrough}
        return data

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Add the YAML file as the lowest-priority file source (below env/.env/secrets).
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )
