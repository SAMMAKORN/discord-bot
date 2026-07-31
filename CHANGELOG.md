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
