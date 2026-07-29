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
    # Shared HTTP/SOCKS proxy used for YouTube transcript requests.
    proxy_url: str = ""

    # Max successful Gemini calls per user per UTC day. 0 disables the gate.
    # Cached responses do not count against this limit; only fresh API hits do.
    insight_rate_limit_per_day: int = 50

    # --- /tldr settings ---

    # Primary OpenAI-compatible AI endpoint (auth2api/A2A).
    gateway_base_url: str = "http://0.0.0.0:8317/v1"
    gateway_api_key: str = ""
    # Optional OpenRouter fallback. Leave openrouter_api_key empty until configured.
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    # a2a, openrouter, or auto (A2A with OpenRouter fallback).
    ai_route_mode: str = "auto"

    # OpenAI-compatible model string routed through A2A.
    # The admin TLDR setting is the source of truth; this is only a bootstrap fallback.
    tldr_llm_model: str = ""

    # Max context characters sent to the LLM for /tldr (web pages can be huge)
    tldr_max_content_chars: int = 40_000

    # Max successful /tldr calls per user per UTC day. 0 disables.
    tldr_rate_limit_per_day: int = 20
    github_token: str | None = None

    # --- GitHub write access (star/unstar) ---
    # Separate OAuth App with public_repo scope. Leave empty to disable gh_write feature.
    github_oauth_public_repo_client_id: str = ""
    github_oauth_public_repo_client_secret: str = ""
