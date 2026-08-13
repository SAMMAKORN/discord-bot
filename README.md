# LiteLLM Usage Discord Bot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Discord bot for checking LiteLLM proxy usage and browsing available models via slash commands. Users register their virtual key on first use, and the bot queries the LiteLLM proxy API to display spend (in USD & THB), models, rate limits, expiry, and more — all as ephemeral ("Only you can see this message") responses.

## Requirements

- Python 3.12+
- A Discord Bot Token
- A LiteLLM Proxy Master Key

## Setup

### 1. Create a Virtual Environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
```

### 2. Install Dependencies

```bash
pip install -r requirements.lock
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your tokens:

```bash
cp .env.example .env
```

```env
BOT_TOKEN=your_discord_bot_token
MASTER_KEY=your_litellm_master_key
LITELLM_BASE_URL=https://litellm.domain.ai
DB_PATH=users.db
ENCRYPTION_KEY_FILE=.encryption_key
# Production: generate once with Fernet.generate_key() and store as a secret
# ENCRYPTION_KEY=your_url_safe_fernet_key
```

> ⚠️ `.env` is git-ignored — never commit it.

### 4. Run the Bot

```bash
python main.py
```

## Commands

All responses are **ephemeral** (only visible to the user who invoked the command).

| Command        | Description                                                                   |
| -------------- | ----------------------------------------------------------------------------- |
| `/help`        | Show all available commands with interactive buttons                          |
| `/usage`       | View usage stats (first time: explains storage, then asks for your key)       |
| `/usage-daily` | View today's usage dashboard (team API: spend, tokens, requests)              |
| `/models`      | List all models you have access to (first time: prompts for your virtual key) |
| `/reset-key`   | Replace your registered virtual key                                           |
| `/delete-key`  | Delete your virtual key and all data from the bot                             |

## `/help` Command

The `/help` command displays an embed listing all available commands, along with **interactive buttons** that let you trigger each command directly without typing:

| Button             | Action                                                    |
| ------------------ | --------------------------------------------------------- |
| **📊 Usage Stats** | Runs `/usage` to check your LiteLLM usage statistics      |
| **🪙 Daily Usage** | Runs `/usage-daily` to check today's usage dashboard      |
| **🤖 Models**      | Runs `/models` to list all accessible AI models           |
| **🔑 Reset Key**   | Opens a modal to reset/update your virtual key            |
| **🗑️ Delete Key**  | Deletes your registered virtual key and data from the bot |

> The buttons remain interactive for 120 seconds after the `/help` response is sent.

## `/models` Command

The `/models` command groups accessible models by provider and clearly labels input/output token limits and input/output price per 1M tokens. Large result sets use Previous/Next pagination and remain within Discord's embed limits.

## `/usage-daily` Command

The `/usage-daily` command displays today's usage dashboard for your virtual key. It resolves the team directly from `/key/info`, then queries `/team/daily/activity` and shows:

- **Total Requests** — Combined successful and failed API requests for today.
- **Total Tokens** — Sum of prompt + completion tokens consumed today.
- **Total Spend** — USD + THB cost for today's usage (live exchange rate).
- **Successful / Failed** — Breakdown of request outcomes.
- **Avg/request** — Average tokens and cost per request.

Timestamps use **Bangkok time** (Asia/Bangkok timezone). Spend includes both USD and THB conversions. This command is useful for tracking daily team-level consumption without the spend/budget details shown by `/usage`.

## Embed Fields

The `/usage` command displays a rich embed with the following fields:

| Field              | Description                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------------- |
| **🔑 Virtual Key** | Truncated virtual key (last 8 chars)                                                                        |
| **🏷️ Key Alias**   | Key alias (if set in LiteLLM proxy)                                                                         |
| **💰 Total Spend** | Spend in USD + converted THB (live exchange rate from [exchangerate API](https://www.exchangerate-api.com)) |
| **📅 Expires**     | Key expiration date                                                                                         |
| **🕐 Last Active** | Last API call time (converted to Asia/Bangkok timezone)                                                     |
| **⚡ Rate Limits** | RPM, TPM, and max parallel requests limits                                                                  |
| **💵 Max Budget**  | Per-key budget cap (if configured)                                                                          |
| **🤖 Models**      | Allowed models (or "All models")                                                                            |
| **⚙️ Config**      | Additional key configuration (if any)                                                                       |

## How It Works

1. **First run** — User types `/usage`, `/usage-daily`, or `/models` → bot explains how the key is used, stored, replaced, and deleted → the user opens the modal → the key is validated against LiteLLM → the verified key is **encrypted with Fernet** and saved to SQLite.
2. **Subsequent runs** — `/usage` or `/models` looks up the stored key, **decrypts it**, and fetches data immediately.
3. **`/reset-key`** — Opens a modal to replace the stored virtual key.
4. **`/delete-key`** — Permanently deletes the user's virtual key and all associated data from the bot's database.

## Security

- **Encrypted at rest** — Virtual keys are encrypted with Fernet (AES-128-CBC) before being written to SQLite. Decrypted only in memory when needed.
- **`ENCRYPTION_KEY`** — In production, set this to a persistent value generated by `Fernet.generate_key()`. Invalid values fail during startup.
- **Secure fallback file** — When the environment secret is omitted, the bot generates a `0600` key file at `ENCRYPTION_KEY_FILE`. Docker keeps it in the persistent data volume.
- **Ephemeral responses** — All command responses are visible only to the user who invoked them.
- **Validated updates** — New/reset keys are verified before replacing stored data.

## Connection to Discord

The bot connects to Discord via WebSocket (`gateway.discord.gg`). No public IP or reverse proxy is required — it runs from any machine with internet access.

For always-online deployment, host on a VPS (Render, Railway, DigitalOcean, etc.).

## Creating a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → give it a name → **Create**
3. Navigate to **Bot** → **Add Bot** → copy the token
4. Navigate to **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`
5. Open the **Generated URL** → select your server → **Authorize**

## Project Structure

```
├── main.py            # Bot entry point (config + bot.run)
├── bot/               # Application modules
│   ├── __init__.py
│   ├── api.py         # LiteLLM proxy API client (shared HTTP session)
│   ├── commands.py    # Slash commands, buttons, modals, views
│   ├── crypto.py      # Fernet encryption for virtual keys
│   ├── db.py          # Async SQLite layer (aiosqlite)
│   └── embeds.py      # Discord embed formatters
├── requirements.txt   # Direct Python dependencies
├── requirements.lock  # Fully resolved, reproducible runtime dependencies
├── requirements-dev.txt # Pinned CI/development tools
├── pyproject.toml      # Ruff configuration
├── tests/              # Automated unit and edge-case tests
├── .github/workflows/ci.yml # CI checks
├── Dockerfile         # Docker build (includes HEALTHCHECK)
├── docker-compose.yml # Local / Coolify compose (named volume: discord-bot-data)
├── .dockerignore
├── .env               # Secrets (git-ignored)
├── .env.example       # Template for .env
├── .gitignore
├── CHANGELOG.md       # Version history
├── bot.db             # SQLite database (local dev only, git-ignored)
└── README.md
```

## Deployment

### Docker (Coolify)

1. Push this repo to a Git provider (GitHub, GitLab, etc.)
2. In Coolify, set **Build Pack** to **Docker Compose** and point to `docker-compose.yml`
3. Configure the following **environment variables** in Coolify's environment settings:

| Variable           | Required | Default                     |
| ------------------ | -------- | --------------------------- |
| `BOT_TOKEN`        | Yes      | —                           |
| `MASTER_KEY`       | Yes      | —                           |
| `LITELLM_BASE_URL` | No       | `https://litellm.domain.ai` |
| `DB_PATH`          | No       | `/app/data/bot.db`          |
| `ENCRYPTION_KEY`   | Recommended | Auto-generated in persistent storage |
| `ENCRYPTION_KEY_FILE` | No    | `/app/data/.encryption_key` |

4. Coolify will build and deploy the bot. Database is persisted via a **named Docker volume** (`discord-bot-data` → `/app/data`) and survives redeployments automatically.

> **⚠️ Important:** Do **not** set `DB_PATH` to a bare filename (e.g. `users.db`). Always use `/app/data/bot.db` so the file is written inside the persistent volume.

### Healthcheck

The Dockerfile includes a built-in healthcheck:

```
Interval: 60s | Timeout: 10s | Start period: 30s | Retries: 3
```

The bot is the container's foreground process, so a running container confirms the process is alive. The healthcheck additionally verifies that `$DB_PATH` exists and SQLite can read it. It uses Python only and does not require `procps`.

If the container becomes **unhealthy**, Coolify/Docker will automatically restart it.

### Local Docker

```bash
cp .env.example .env
# Fill in .env with your tokens (use DB_PATH=users.db for local dev)
docker compose up --build -d
```

## Tech Stack

| Component        | Technology                                           |
| ---------------- | ---------------------------------------------------- |
| Runtime          | Python 3.12+                                         |
| Discord Library  | discord.py 2.x                                       |
| HTTP Client      | aiohttp (shared async session)                       |
| Database         | aiosqlite (non-blocking async SQLite)                |
| Encryption       | cryptography (Fernet symmetric encryption)           |
| Config           | python-dotenv (environment variable loading)         |
| Timezone         | tzdata (Asia/Bangkok timezone support)               |
| Containerization | Docker + Docker Compose                              |

## Development Checks

Install the pinned development toolchain and run the same checks as CI:

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
python -m unittest discover -v
bandit -q -r bot main.py
pip-audit -r requirements.lock
```

GitHub Actions runs linting, formatting, unit tests, security scanning, and dependency auditing for every push and pull request.

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

Copyright © 2026 Sammakorn Public Co. Ltd.
