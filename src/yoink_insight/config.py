"""Insight plugin configuration."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class InsightConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gemini API key from https://aistudio.google.com
    gemini_api_key: str = ""

    # Model to use for summarization
    gemini_model: str = "gemini-2.0-flash"

    # Default language for new access grants
    insight_default_lang: str = "en"

    # Transcript languages to try, in order (comma-separated)
    insight_transcript_langs: str = "en,ru"

    # Max successful Gemini calls per user per UTC day. 0 disables the gate.
    # Cached responses do not count against this limit; only fresh API hits do.
    insight_rate_limit_per_day: int = 50
