# v1.0.0 — LiteLLM Usage Discord Bot

## Overview

A Discord bot that checks LiteLLM proxy usage via the `/usage` slash command. Users register their virtual key on first use, and the bot queries the LiteLLM proxy API to display spend (USD + THB), rate limits, key alias, expiry, and more — all as ephemeral responses visible only to the user.

## Features

### Commands
- **`/usage`** — View your LiteLLM usage stats. First time: prompts for your virtual key via modal.
- **`/reset-key`** — Replace your registered virtual key.

### Embed Fields
The `/usage` command displays a rich embed with:
- 🔑 **Virtual Key** — Truncated (last 8 chars)
- 🏷️ **Key Alias** — Key alias if set in proxy
- 💰 **Total Spend** — USD + converted THB (live exchange rate)
- 📅 **Expires** — Key expiration date
- 🕐 **Last Active** — Last API call (Asia/Bangkok timezone)
- ⚡ **Rate Limits** — RPM, TPM, max parallel requests
- 💵 **Max Budget** — Per-key budget cap
- 🤖 **Models** — Allowed models
- ⚙️ **Config** — Additional key configuration

### Privacy
All command responses are **ephemeral** ("Only you can see this message").

## Deployment

### Local (Python)
```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

### Docker (Coolify)
1. Push this repo to a Git provider
2. Add a new project in Coolify
3. Set environment variables:
   - `BOT_TOKEN` (required)
   - `MASTER_KEY` (required)
   - `LITELLM_BASE_URL` (default: `https://litellm.sam.co.th`)
   - `DB_PATH` (default: `/app/data/bot.db`)

### Environment Variables
| Variable           | Required | Default                     |
| ------------------ | -------- | --------------------------- |
| `BOT_TOKEN`        | Yes      | —                           |
| `MASTER_KEY`       | Yes      | —                           |
| `LITELLM_BASE_URL` | No       | `https://litellm.sam.co.th` |
| `DB_PATH`          | No       | `/app/data/bot.db`          |

## Changelog

## v1.4.0 — Module Architecture, Async SQLite, and Encrypted Key Storage

### Added
- **`bot/` package** — Monolith split into modular structure:
  - `bot/api.py` — LiteLLM proxy API client with shared `aiohttp.ClientSession`
  - `bot/db.py` — Async SQLite layer using `aiosqlite` (non-blocking)
  - `bot/crypto.py` — Fernet-based symmetric encryption for virtual keys at rest
  - `bot/embeds.py` — Discord embed formatters (usage, models, daily usage, help)
  - `bot/commands.py` — Slash commands, buttons, modals, views
- **Encrypted key storage** — Virtual keys are encrypted with Fernet (AES-128-CBC) before being written to SQLite. Decrypted on read. Auto-migrates legacy plaintext keys on first boot.
- **`ENCRYPTION_KEY` env var** — Optional. If set, uses the provided key for encryption. If omitted, auto-generates and stores locally (single-instance only).
- **Graceful shutdown** — Handles SIGINT/SIGTERM to close HTTP session and DB connection cleanly.
- **Auto-migration** — On first boot, plaintext keys starting with `sk-` are automatically re-encrypted.

### Changed
- **SQLite → aiosqlite** — All database calls are now async, eliminating event-loop blocking.
- **HTTP session pooling** — Shared `aiohttp.ClientSession` across all API calls instead of creating a new session per request.
- `aiosqlite` and `cryptography` added to `requirements.txt`.
- `.dockerignore` and `.gitignore` updated to exclude `.encryption_key`.

### Removed
- Synchronous `sqlite3` calls replaced with `aiosqlite`.
- Per-request `aiohttp.ClientSession` creation in `api.py`.

## v1.3.0 — Team API Migration, Key Alias Suffix Matching, and Robustness

### Changed
- **Renamed `/usage-token` to `/usage-daily`** — the command now uses the team API (`/team/list` + `/team/daily/activity`) to display today's usage dashboard (total requests, tokens, spend, successful/failed breakdown, per-request averages) instead of showing all-time token consumption.
- Help command and button labels updated to reflect the new command name ("Daily Usage").
- **Team API migration** — `/usage-daily` resolves the user's key through `/team/list` to find the associated team, then queries `/team/daily/activity` for granular daily metrics (prompt tokens, completion tokens, successful/failed requests, per-request averages).
- **Key alias suffix matching** — `_extract_key_metrics` falls back to matching the last 8 characters of the key alias when an exact match is not found in the team activity breakdown, ensuring keys with truncated or reformatted aliases still resolve correctly.
- **Silent-zeros warning** — when `format_token_usage_embed` finds no activity data for the day, it adds a warning field ("No activity data found for today. The dashboard will show zeroes.") so users are not misled by blank-looking dashboards.

### Fixed
- **Latent bug in `_resolve_team_info`** — when `key_info["info"]` contained a `team_id` that was not present in the team list returned by `/team/list`, the function now returns a result with `"team_alias": "Unknown"` and the known `team_id` instead of returning `None` and leaving the user with an unhelpful error. This prevents the `/usage-daily` command from failing when the team list is incomplete or stale.

## v1.0.0 — LiteLLM Usage Discord Bot

### Added
- SQLite database for per-user virtual key storage
- Rich embed with key info, spend, rate limits, models, and config
- THB currency conversion using live exchange rate (exchangerate API)
- Asia/Bangkok timezone for Last Active timestamp
- Ephemeral responses for all commands
- Docker support (Dockerfile, docker-compose.yml)
- Coolify deployment guide

### Changed
- None (initial release)

### Fixed
- None (initial release)

## Tech Stack
- Python 3.12+
- discord.py 2.x
- aiohttp (async HTTP)
- SQLite (per-user keys)
- python-dotenv (environment config)
- tzdata (timezone support)
