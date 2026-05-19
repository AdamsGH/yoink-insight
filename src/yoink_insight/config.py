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

    # --- /tldr settings ---

    # Gateway base URL for YouTube transcript fetching (POST /youtube/transcript)
    # and for the OpenAI-compatible LLM calls used by /tldr.
    gateway_base_url: str = "http://gateway:4060"
    gateway_api_key: str = ""

    # OpenAI-compatible model string routed through the gateway (e.g. cpa/anthropic/claude-haiku-4-5)
    tldr_llm_model: str = "cpa/anthropic/claude-haiku-4.5"

    # Max context characters sent to the LLM for /tldr (web pages can be huge)
    tldr_max_content_chars: int = 40_000

    # Max successful /tldr calls per user per UTC day. 0 disables.
    tldr_rate_limit_per_day: int = 20
