"""Environment settings (R15): ``SCRAPPY_*`` variables and ``.env``; secrets only from env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import AliasChoices, Field, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"
"""Cheap and reliable at JSON structured output on OpenRouter. Override: SCRAPPY_LLM_MODEL."""
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRAPPY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- paths
    data_dir: Path = Path("data")
    config_dir: Path = Path("config")
    database_url: str = ""
    """Defaults to ``sqlite+aiosqlite:///<data_dir>/scrappy.db``."""
    archive_dir: Path | None = None
    """Raw page archive; defaults to ``<data_dir>/raw``."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- LLM. Profiles live in config/extraction.yaml (ADR 0010); without that file one
    # ``openrouter`` profile is derived from these SCRAPPY_LLM_* values.
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "SCRAPPY_OPENROUTER_API_KEY"),
    )
    llm_model: str = DEFAULT_LLM_MODEL
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_timeout: float = Field(default=60.0, gt=0)
    """Seconds per request."""
    llm_max_description_chars: int = Field(default=4000, ge=100)
    llm_structured_output: bool = True
    """Ask for ``json_schema`` structured output; falls back to ``json_object`` if rejected."""
    llm_referer: str | None = None
    """Optional OpenRouter ``HTTP-Referer`` header."""
    llm_app_title: str | None = "olx_scrappy"
    """Optional OpenRouter ``X-Title`` header."""

    # --- worker
    worker_poll_interval: float = Field(default=2.0, gt=0)
    """Seconds to sleep when the queue is empty."""
    worker_batch_size: int = Field(default=10, ge=1)

    # --- pipeline
    pipeline_discovery_max_pages: int = Field(default=100, ge=1)
    pipeline_retry_max_attempts: int = Field(default=5, ge=1)

    _secrets_file: Path | None = PrivateAttr(default=None)
    """The ``.env`` file these settings were read from (``None`` = none); ``secret`` uses it."""

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        env_file = values.get("_env_file", self.model_config.get("env_file"))
        self._secrets_file = Path(env_file) if isinstance(env_file, str | Path) else None

    @model_validator(mode="after")
    def _derive_defaults(self) -> Settings:
        if not self.database_url:
            posix = self.data_dir.resolve().as_posix()
            self.database_url = f"sqlite+aiosqlite:///{posix}/scrappy.db"
        if self.archive_dir is None:
            self.archive_dir = self.data_dir / "raw"
        return self

    @property
    def categories_file(self) -> Path:
        return self.config_dir / "categories.yaml"

    @property
    def sources_file(self) -> Path:
        return self.config_dir / "sources.yaml"

    @property
    def extraction_file(self) -> Path:
        return self.config_dir / "extraction.yaml"

    def secret(self, name: str) -> str | None:
        """A secret named by config (``api_key_env``): the environment first, then the
        ``.env`` file these settings were read from. ``OPENROUTER_API_KEY`` comes from the
        settings field (which also covers its ``SCRAPPY_`` alias and the ``.env`` file)."""
        if name == "OPENROUTER_API_KEY":
            key = self.openrouter_api_key
            return None if key is None else key.get_secret_value() or None
        value = os.environ.get(name)
        if value:
            return value
        env_file = self._secrets_file
        if env_file is not None and env_file.is_file():
            return dotenv_values(env_file).get(name) or None
        return None
