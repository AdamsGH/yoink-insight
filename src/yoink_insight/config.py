"""Insight plugin configuration."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class InsightConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Path to the gemini CLI binary; defaults to just "gemini" (on PATH)
    gemini_cli_path: str = "gemini"

    # If set, use this as the HOME env var when spawning the gemini subprocess.
    # Useful in Docker where the host's ~/.config/gemini/ is mounted elsewhere.
    gemini_home: str | None = None

    # Default language for new access grants when no lang is specified
    insight_default_lang: str = "en"

    # Timeout in seconds for the gemini subprocess
    insight_timeout: int = 60
