# yoink-insight

AI-powered content insights plugin for [yoink-core](https://github.com/AdamsGH/yoink-core).

Two independent features, each with its own RBAC grant:

- **AI Summary** (`insight:summary`) - YouTube transcript summarisation via Gemini.
- **TLDR** (`insight:tldr`) - Summarise any URL (YouTube or web page) via a gateway-routed OpenAI-compatible LLM (default: `claude-haiku-4-5` through the local gateway).

Included in yoink-core as a git submodule at `plugins/yoink-insight`.

## Bot commands

| Command | Feature gate | Scope | Description |
|---|---|---|---|
| `/summary <url>` | `insight:summary` | any | Bullet-point summary of a YouTube video |
| `/about <url>` | `insight:summary` | any | 2-3 sentence description of a YouTube video |
| `/tldr <url> [question]` | `insight:tldr` | any | Summarise any URL; optional focus question steers the answer |
| `/insight_lang <code>` | `insight:summary` | private | Set preferred response language |
| `/insight_grant <id>` | admin | private | Grant Insight access to a user |
| `/insight_revoke <id>` | admin | private | Revoke Insight access |
| `/insight_list` | admin | private | List users with access |

`/tldr` accepts YouTube links, web articles, or any publicly reachable URL. For YouTube it fetches the transcript from the gateway (`POST /youtube/transcript`); for other URLs it fetches HTML with httpx and extracts main text via trafilatura.

## RBAC

Two `FeatureSpec` objects, both `default_min_role=None` (explicit grant required; owner always passes):

| Feature | Label | Description |
|---|---|---|
| `insight:summary` | AI Summary | `/summary` and `/about` commands |
| `insight:tldr` | TLDR | `/tldr` command |

Grants are managed via:
- Web dashboard: admin users panel (Permissions tab per user)
- Bot commands: `/insight_grant`, `/insight_revoke`
- API: `POST/DELETE /api/v1/insight/access/{uid}`

The two features are independent: a user can have `insight:tldr` without `insight:summary`.

## TLDR - how it works

```
/tldr <url> [question]
       |
       +-- YouTube? --> gateway POST /youtube/transcript (cascade: transcript_api -> yt-dlp + bgutil POT)
       |
       +-- Web page --> httpx GET + trafilatura text extraction
       |
       v
   Prompt -> gateway POST /v1/chat/completions (OpenAI-compatible, streaming)
       |
       v
   Streaming draft via sendMessageDraft -> final edit_text
       |
       v
   Cache in insight_summary_cache (content_key=url, command="tldr")
```

Responses stream progressively via Telegram's `sendMessageDraft` extension (same as `/summary`). The LLM model is per-user configurable from an admin-curated allowed list.

## Web dashboard

| Path | Role | Description |
|---|---|---|
| `/insight/settings` | user | Language picker + TLDR model selector (if access granted) |
| `/admin/insight-access` | admin | Grant/revoke Insight access, search users |
| `/admin/insight-tldr` | admin | Configure allowed LLM models and default for /tldr |

### TLDR model config (`/admin/insight-tldr`)

Admins/owners define the list of models users can choose from and set the default. Owner always sees all models from `GET /v1/models` on the gateway; regular admins see the current allowed list.

Stored in `bot_settings` under keys `insight_tldr_allowed_models` (JSON array) and `insight_tldr_default_model`.

## Configuration

All variables come from `.env` via `InsightConfig(BaseSettings)`.

### AI Summary

| Variable | Required | Default | Description |
|---|---|---|---|
| `gemini_api_key` | yes | - | Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `gemini_model` | no | `gemini-2.0-flash` | Model for /summary and /about |
| `insight_default_lang` | no | `en` | Default language for new users |
| `insight_transcript_langs` | no | `en,ru` | Transcript language preference order (youtube-transcript-api) |
| `insight_rate_limit_per_day` | no | `50` | Per-user daily Gemini call cap (fresh API hits only; cache hits free) |

### TLDR

| Variable | Required | Default | Description |
|---|---|---|---|
| `gateway_base_url` | no | `http://gateway:4060` | Base URL for gateway (transcript + LLM) |
| `gateway_api_key` | no | - | API key for gateway requests (`X-API-Key` / `Authorization: Bearer`) |
| `tldr_llm_model` | no | `cpa/anthropic/claude-haiku-4-5` | Default LLM model string (overridden by admin config and per-user choice) |
| `tldr_max_content_chars` | no | `40000` | Max characters of extracted web content sent to LLM |
| `tldr_rate_limit_per_day` | no | `20` | Per-user daily /tldr cap (fresh API hits only; 0 disables) |

## API endpoints

Mounted at `/api/v1/insight/`. Auth: JWT Bearer token.

### Access management (admin)

| Method | Path | Description |
|---|---|---|
| GET | /access | List all users with Insight access |
| POST | /access/{uid} | Grant access |
| PATCH | /access/{uid} | Update language for user |
| DELETE | /access/{uid} | Revoke access |
| GET | /access/lookup?q= | Search users by @username or ID |

### User settings

| Method | Path | Description |
|---|---|---|
| GET | /settings/me | Own settings: lang, access flags, tldr_model, tldr_allowed_models |
| PATCH | /settings/me | Update lang and/or tldr_model |

`PATCH /settings/me` body: `{ "lang": "ru", "tldr_model": "cpa/anthropic/claude-haiku-4-5" }`. Non-owner users can only set a model from the admin-configured allowed list.

### TLDR config (admin/owner)

| Method | Path | Description |
|---|---|---|
| GET | /config/tldr | Current allowed_models list and default_model |
| PATCH | /config/tldr | Update allowed_models and default_model |

Body: `{ "allowed_models": ["cpa/anthropic/claude-haiku-4-5", "or/openai/gpt-4o-mini"], "default_model": "cpa/anthropic/claude-haiku-4-5" }`.

### Models

| Method | Path | Description |
|---|---|---|
| GET | /models | Allowed models for current user (owner: all gateway models) |

### Stats

| Method | Path | Description |
|---|---|---|
| GET | /me/stats | Own usage stats (totals, by-command, daily history 30 days) |

## Database

Single Alembic chain. Insight-relevant migrations:

| Migration | Description |
|---|---|
| 0009 | `insight_access` table (legacy allowlist) |
| 0012 | `user_permissions` table (core RBAC; replaces dual-write) |
| 0013 | `insight_user_settings` table |
| 0033 | `insight_summary_cache` table |
| 0035 | `insight_summary_cache.video_id` renamed to `content_key VARCHAR(512)` to support non-YouTube URLs |
| 0036 | `insight_user_settings.tldr_model VARCHAR(128)` per-user LLM model override |

### Schema

```sql
insight_user_settings (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    lang       VARCHAR(8)   NOT NULL DEFAULT 'en',
    tldr_model VARCHAR(128)          -- NULL = use admin default
)

insight_summary_cache (
    id          SERIAL PRIMARY KEY,
    content_key VARCHAR(512) NOT NULL,   -- video ID for /summary,/about; normalized URL for /tldr
    lang        VARCHAR(8)   NOT NULL,
    command     VARCHAR(16)  NOT NULL,   -- 'summary' | 'about' | 'tldr'
    result      TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL,
    expires_at  TIMESTAMPTZ  NOT NULL,
    UNIQUE (content_key, lang, command)
)

insight_usage_log (
    id         SERIAL PRIMARY KEY,
    user_id    BIGINT      REFERENCES users(id) ON DELETE CASCADE,
    command    VARCHAR(16) NOT NULL,
    video_id   VARCHAR(32),
    lang       VARCHAR(8)  NOT NULL,
    status     VARCHAR(16) NOT NULL,   -- 'ok' | 'error' | 'cached'
    error_code VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL
)
```

Cache TTL is 24 hours. For `/summary`/`/about` the cache key is the bare YouTube video ID (shared between commands for the same video). For `/tldr` the key is the normalized URL (`scheme://host/path`, no query/fragment).

Rate limits are enforced per-command: `/summary`+`/about` share `insight_rate_limit_per_day`; `/tldr` has its own `tldr_rate_limit_per_day`. Cache hits never count against either limit.

## Package structure

```
src/yoink_insight/
  plugin.py              # InsightPlugin entry point
  config.py              # InsightConfig (pydantic-settings)
  api/
    router.py            # FastAPI routes
    schemas.py           # Pydantic request/response models
  bot/middleware.py      # bot_data helpers (get_insight_config etc.)
  commands/
    _runner.py           # shared streaming runner (summary/about)
    summary.py           # /summary handler
    about.py             # /about handler
    tldr.py              # /tldr handler
    access.py            # /insight_grant, /insight_revoke, /insight_list
    settings.py          # /insight_lang handler
  services/
    gemini.py            # GeminiSummarizer: transcript (asyncio.to_thread) + Gemini streaming
    tldr.py              # TldrService: gateway transcript + httpx/trafilatura + OpenAI-compat streaming
    access.py            # InsightAccessService - reads core user_permissions
  storage/
    models.py            # ORM models
    repos.py             # InsightSummaryCacheRepo, InsightUserSettingsRepo, InsightAccessRepo, InsightUsageLogRepo
  i18n/locales/          # en.yml, ru.yml
frontend/
  manifest.tsx           # route + nav registration
  src/
    api/insight.ts       # typed API client
    pages/
      settings/index.tsx      # language picker + TLDR model selector
      admin/TldrConfigPage.tsx # allowed models config
```
