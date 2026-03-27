# yoink-insight

AI-powered YouTube video insights plugin for [yoink-core](https://github.com/AdamsGH/yoink-core).

Fetches a video transcript via `youtube-transcript-api` and summarizes it with the Gemini API.

Included in yoink-core as a git submodule at `plugins/yoink-insight`.

## Bot commands

| Command | Scope | Description |
|---|---|---|
| `/summary <url>` | any | Bullet-point summary of a YouTube video |
| `/about <url>` | any | 2-3 sentence description |
| `/insight_lang <code>` | private | Set your preferred response language |
| `/insight_grant <id>` | private | Grant Insight access to a user (admin) |
| `/insight_revoke <id>` | private | Revoke Insight access (admin) |
| `/insight_list` | private | List users with access (admin) |

## RBAC

`FeatureSpec(insight:summary, default_min_role=None)` - explicit grant required for all users except the bot owner.

Access is managed via:
- Bot commands: `/insight_grant`, `/insight_revoke` (admin)
- Web dashboard: `/admin/insight-access`
- API: `POST/DELETE /api/v1/insight/access/{uid}` (admin)

## Web dashboard

| Path | Role | Description |
|---|---|---|
| `/insight/settings` | user | Language picker |
| `/admin/insight-access` | admin | Grant/revoke access, search users, edit language inline |

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `gemini_api_key` | yes | - | Gemini API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `gemini_model` | no | `gemini-3-flash-preview` | Model for summarization |
| `insight_default_lang` | no | `en` | Default language for new users |
| `insight_transcript_langs` | no | `en,ru` | Transcript language preference order |

Free tier from AI Studio is sufficient for personal use (no billing required).

## API endpoints

Mounted at `/api/v1/insight/`. Auth: JWT Bearer token.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | /access | admin | List all users with access |
| POST | /access/{uid} | admin | Grant access |
| PATCH | /access/{uid} | admin | Update language |
| DELETE | /access/{uid} | admin | Revoke access |
| GET | /access/lookup?q= | admin | Search users by @username or ID |
| GET | /settings/me | user | Get own language setting |
| PATCH | /settings/me | user | Update own language |

## Database

Migration `0009_insight_plugin_schema` adds `insight_access`. Migration `0013_insight_user_settings` adds `insight_user_settings`.

```sql
insight_access (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    lang       VARCHAR(8) NOT NULL DEFAULT 'en',
    granted_by BIGINT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL
)

insight_user_settings (
    user_id    BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    lang       VARCHAR(8) NOT NULL DEFAULT 'en',
    updated_at TIMESTAMPTZ NOT NULL
)
```

## Package structure

```
src/yoink_insight/
  plugin.py              # entry point (InsightPlugin)
  config.py              # InsightConfig (pydantic-settings)
  api/router.py          # FastAPI routes
  bot/middleware.py      # access check middleware
  commands/
    summary.py           # /summary handler
    about.py             # /about handler
    access.py            # /insight_grant, /insight_revoke, /insight_list
    settings.py          # /insight_lang handler
  services/
    gemini.py            # GeminiSummarizer: transcript fetch + Gemini API call
    access.py            # InsightAccessService
  storage/
    models.py            # InsightAccess, InsightUserSettings ORM models
    repos.py             # InsightAccessRepo, InsightUserSettingsRepo
  i18n/locales/          # translations (en.yml, ru.yml)
frontend/
  manifest.tsx           # route registration
  src/pages/
    settings/index.tsx   # language picker
    admin/access/index.tsx  # access management dashboard
```
