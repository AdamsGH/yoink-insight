# yoink-insight

AI-powered YouTube video insights plugin for [yoink-core](https://github.com/AdamsGH/yoink-core).

Fetches a video transcript via `youtube-transcript-api` and summarizes it with the Gemini API.

## Commands

| Command | Description |
|---|---|
| `/summary <url>` | Bullet-point summary of a YouTube video |
| `/about <url>` | 2-3 sentence description of a YouTube video |
| `/insight_lang <code>` | Set your preferred response language |
| `/insight_grant <id>` | Grant Insight access to a user (admin) |
| `/insight_revoke <id>` | Revoke Insight access (admin) |
| `/insight_list` | List users with access (admin) |

## Access control

Access is per-user via the `insight_access` table. The bot owner always has access. Everyone else must be explicitly granted by an admin or owner - either via bot commands or the web dashboard.

## Web dashboard

- `/insight/settings` - language picker for the current user
- `/admin/insight-access` - grant/revoke access, search users by `@username`, inline language editing (admin/owner)

## Configuration

Add to `.env` in yoink-core:

```env
yoink_plugins=...,insight
gemini_api_key=AIza...         # from https://aistudio.google.com/apikey
gemini_model=gemini-3-flash-preview
insight_default_lang=en
insight_transcript_langs=en,ru
```

### Variables

| Variable | Default | Description |
|---|---|---|
| `gemini_api_key` | - | Gemini API key (required) |
| `gemini_model` | `gemini-3-flash-preview` | Model to use for summarization |
| `insight_default_lang` | `en` | Default language for new users |
| `insight_transcript_langs` | `en,ru` | Transcript language preference order |

Get a free API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The free tier is sufficient for personal use (no billing required).

## REST API

Mounted at `/api/v1/insight/`. Requires JWT auth.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | /access | admin | List all users with access (includes username/name) |
| POST | /access/{uid} | admin | Grant access |
| PATCH | /access/{uid} | admin | Update language |
| DELETE | /access/{uid} | admin | Revoke access |
| GET | /access/lookup?q= | admin | Search users by @username or ID |
| GET | /settings/me | user | Get own language setting |
| PATCH | /settings/me | user | Update own language |

## Database

Migration `0009_insight_plugin_schema` adds one table:

```sql
insight_access (
    user_id   BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    lang      VARCHAR(8) NOT NULL DEFAULT 'en',
    granted_by BIGINT NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL
)
```

## Architecture

- **`services/gemini.py`** - `GeminiSummarizer`: fetches transcript, calls Gemini API via `google-genai`
- **`commands/`** - PTB handlers: `summary`, `about`, `access`, `settings`
- **`api/router.py`** - FastAPI routes
- **`storage/`** - SQLAlchemy model + async repo
- **`i18n/locales/`** - en/ru translations
- **`frontend/`** - React pages for web dashboard

## Dependencies

- [`google-genai`](https://pypi.org/project/google-genai/) - Gemini API client
- [`youtube-transcript-api`](https://pypi.org/project/youtube-transcript-api/) - transcript fetching
- `yoink-core` - plugin protocol, DB, auth, i18n
