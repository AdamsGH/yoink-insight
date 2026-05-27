# yoink-insight

AI-powered content insights plugin for [yoink-core](https://github.com/AdamsGH/yoink-core).

Three independent features, each with its own RBAC grant:

- **AI Summary** (`insight:summary`) - YouTube transcript summarisation via Gemini.
- **TLDR** (`insight:tldr`) - Summarise any URL (YouTube or web page) via a gateway-routed OpenAI-compatible LLM (default: `claude-haiku-4-5` through the local gateway).
- **AI Search** (`insight:search`) - Routes summary/tldr requests through the gateway answer engine for web-search-enhanced results.

Included in yoink-core as a git submodule at `plugins/yoink-insight`.

## Bot commands

| Command | Feature gate | Scope | Description |
|---|---|---|---|
| `/about <url>` | `insight:summary` | any | Describe a YouTube video (2-3 sentences) |
| `/summary <url>` | `insight:summary` | any | Summarize a YouTube video (bullet points) |
| `/tldr <url> [question]` | `insight:tldr` | any | Summarize any URL (+ max / nobullshit / tale modifiers) |
| `/insight_lang <code>` | `insight:summary` | private | Set Insight language |
| `/insight_grant <id>` | admin | private | Grant Insight access |
| `/insight_revoke <id>` | admin | private | Revoke Insight access |
| `/insight_list` | admin | private | List Insight access |

`/tldr` accepts YouTube links, web articles, or any publicly reachable URL. For YouTube it fetches the transcript from the gateway (`POST /youtube/transcript`); for other URLs it fetches HTML with httpx and extracts main text via trafilatura.

## RBAC

Three `FeatureSpec` objects, all `default_min_role=None` (explicit grant required; owner always passes):

| Feature | Label | Description |
|---|---|---|
| `insight:summary` | AI Summary | `/summary` and `/about` commands (YouTube transcript + Gemini) |
| `insight:tldr` | TL;DR | `/tldr` command (any URL summarised via gateway LLM) |
| `insight:search` | AI Search | Routes `/summary`, `/about`, and `/tldr` through the gateway answer engine; enables web-search and smart scrape |

Grants are managed via:
- Web dashboard: admin users panel (Permissions tab per user)
- Bot commands: `/insight_grant`, `/insight_revoke`
- API: `POST/DELETE /api/v1/insight/access/{uid}`

All three features are independent: a user can have `insight:tldr` without `insight:summary`, and `insight:search` without either.

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

## BYOK (Bring Your Own Key)

When the admin flips `insight_byok_enabled` (BotSetting) to `true`, any authorised user can run `/tldr` against their own LLM endpoint, even without the `insight:tldr` grant. Configured per-user via the AI settings page (or `PUT /api/v1/insight/byok/me`).

Supported providers:

| id | default base_url | auth | notes |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `Authorization: Bearer` | live `/models` |
| `anthropic` | `https://api.anthropic.com` | `x-api-key` + `anthropic-version: 2023-06-01` | live `/v1/models`; Messages API streaming, normalised to text deltas |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | `Authorization: Bearer` | OpenAI-compatible shim |
| `openrouter` | `https://openrouter.ai/api/v1` | `Authorization: Bearer` | live `/models`; the `*:online` suffix marks websearch variants |
| `perplexity` | `https://api.perplexity.ai` | `Authorization: Bearer` | hardcoded `sonar*` list; every model treated as websearch-capable |
| `custom_openai` | user-supplied | `Authorization: Bearer` | any OpenAI-compatible endpoint |
| `custom_anthropic` | user-supplied | `x-api-key` | any Anthropic-compatible endpoint |

Web-search capability is detected by model id substrings (`sonar*`, `*:online`, `*-search-preview`, `perplexity/*`) plus `provider.all_websearch=True`. Models that match render with a soft emerald tint and a globe icon; picking a model without the marker triggers a confirmation dialog before save.

The `/tldr` bot handler picks a path automatically (`services.tldr.resolve_tldr_route`):

1. User has an explicit `insight:tldr` grant (user_permissions row) or is owner -> route through the gateway.
2. No gateway grant, BYOK enabled, user has a saved + probed config -> route through the user's provider directly, bypassing the gateway. Every successful call writes `route='byok'` to `insight_usage_log` so analytics can split per path.
3. Otherwise -> reply with `tldr.no_access`.

Both paths count as effective `insight:tldr` access. The `EffectiveFeatureResolver` provider registered in `yoink_insight.plugin.setup` exposes BYOK readiness (global toggle on + saved row + probed key) as a `GrantSource.provider` grant, so BYOK-only users see `/tldr` in `/help` and `setMyCommands` without a `user_permissions` row.

`InsightUserSettingsResponse` exposes two parallel flags per feature: `has_tldr_access` / `has_search_access` (any effective grant) and `has_tldr_gateway_access` / `has_search_gateway_access` (gateway-side grant only, i.e. `GrantSource.owner`, `.explicit`, or `.role`). The web settings page uses the gateway flag to gate the allowed-model picker, the GitHub token field, and the AI Tools `use_search` toggle - BYOK-only users do not see them because their requests bypass the gateway entirely.

### BYOK API

| Method | Path | Description |
|---|---|---|
| GET | `/byok/me` | Current config (api_key masked) + provider catalogue |
| PUT | `/byok/me` | Save provider + base_url + key + model; runs probe + caches model list; calls `refresh_user_commands` |
| DELETE | `/byok/me` | Remove the user's config; calls `refresh_user_commands` |
| POST | `/byok/me/test` | Probe an arbitrary `{provider, base_url, api_key}` triple, returns models with websearch flag |
| POST | `/byok/me/refresh-models` | Re-fetch model list using stored credentials; calls `refresh_user_commands` |
| GET | `/config/byok` | Admin: read global toggle |
| PATCH | `/config/byok` | Admin: write global toggle (`{enabled: bool}`); fans out `refresh_user_commands` to all users with a saved BYOK row |

Every write path calls `refresh_user_commands` because BYOK readiness flips the effective `insight:tldr` grant, which changes the user's `setMyCommands` menu and `/help` output.

### Storage

```sql
insight_user_byok (
    user_id            BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    provider           VARCHAR(32)  NOT NULL,
    base_url           VARCHAR(512),
    api_key            TEXT         NOT NULL,
    model              VARCHAR(128) NOT NULL,
    models_json        TEXT,
    models_fetched_at  TIMESTAMPTZ,
    tested_at          TIMESTAMPTZ,
    test_error         VARCHAR(256),
    created_at         TIMESTAMPTZ  NOT NULL,
    updated_at         TIMESTAMPTZ  NOT NULL
)
```

Keys are stored as plain text; protect the database accordingly. The admin toggle lives in `bot_settings(key='insight_byok_enabled')`.

```sql
insight_user_prompts (
    user_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    command    VARCHAR(16) NOT NULL,   -- 'summary' | 'about' | 'tldr'
    prompt     TEXT        NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, command)
)

insight_tldr_aliases (
    id           SERIAL PRIMARY KEY,
    user_id      BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    aliases      VARCHAR(256),          -- comma-separated keyword(s)
    prompt       TEXT,
    domains      VARCHAR(512),          -- comma-separated fnmatch globs
    target_alias VARCHAR(32),           -- built-in alias to redirect to
    created_at   TIMESTAMPTZ  NOT NULL
)
```

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
| GET | /settings/me | Own settings: lang, access flags, tldr_model, tldr_allowed_models, prompts, aliases |
| PATCH | /settings/me | Update lang, tldr_model, use_search, and per-command prompt overrides |

`PATCH /settings/me` body: `{ "lang": "ru", "tldr_model": "cpa/anthropic/claude-haiku-4-5" }`. Non-owner users can only set a model from the admin-configured allowed list.

### TLDR aliases (user)

| Method | Path | Description |
|---|---|---|
| GET | /aliases | List my /tldr aliases |
| POST | /aliases | Create alias (aliases+prompt, or domain binding to built-in) |
| PATCH | /aliases/{id} | Update alias |
| DELETE | /aliases/{id} | Delete alias |

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
| 0037 | `insight_user_settings.github_token VARCHAR(256)` for GitHub URL support in /tldr |
| 0039 | `insight_tldr_aliases` table (initial: user-defined /tldr prompt aliases) |
| 0040 | `insight_tldr_aliases.alias` renamed to `aliases` column |
| 0041 | `insight_tldr_aliases`: domain bindings and binding-to-built-in rows |
| 0042 | `insight_usage_log`: `content_chars`, `video_seconds`, `alias_key` columns (TLDR metrics) |
| 0043 | `insight_user_prompts` table (per-user default prompt overrides per command) |
| 0044 | `insight_user_settings.use_search` column (AI Search toggle) |
| 0045 | `insight_user_byok` per-user Bring-Your-Own-Key configuration |
| 0046 | `insight_usage_log.route` column (`gateway` default, `byok` for direct-provider calls) |

### Schema

```sql
insight_user_settings (
    user_id       BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    lang          VARCHAR(8)   NOT NULL DEFAULT 'en',
    tldr_model    VARCHAR(128),          -- NULL = use admin default
    github_token  VARCHAR(256),
    use_search    BOOLEAN      NOT NULL DEFAULT false
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
    id             SERIAL PRIMARY KEY,
    user_id        BIGINT      REFERENCES users(id) ON DELETE CASCADE,
    command        VARCHAR(16) NOT NULL,   -- 'summary' | 'about' | 'tldr' | 'tldr:<alias>'
    video_id       VARCHAR(32),
    lang           VARCHAR(8)  NOT NULL,
    status         VARCHAR(16) NOT NULL,   -- 'ok' | 'error' | 'cached'
    error_code     VARCHAR(32),
    created_at     TIMESTAMPTZ NOT NULL,
    content_chars  INTEGER,               -- TLDR: extracted text length
    video_seconds  INTEGER,               -- TLDR: YouTube video duration
    alias_key      VARCHAR(64),           -- TLDR: alias used, if any
    route          VARCHAR(16) NOT NULL   -- 'gateway' (default) | 'byok'
                              DEFAULT 'gateway'
)
```

Cache TTL is 24 hours. For `/summary`/`/about` the cache key is the bare YouTube video ID (shared between commands for the same video). For `/tldr` the key is the normalized URL (`scheme://host/path`, no query/fragment).

Rate limits are enforced per-command: `/summary`+`/about` share `insight_rate_limit_per_day`; `/tldr` has its own `tldr_rate_limit_per_day`. Cache hits never count against either limit.
