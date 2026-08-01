# LiteLLM Usage Discord Bot

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
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your tokens:

```bash
cp .env.example .env
```

```env
BOT_TOKEN=your_discord_bot_token
MASTER_KEY=your_litellm_master_key
LITELLM_BASE_URL=https://litellm.sam.co.th
DB_PATH=users.db
```

> ⚠️ `.env` is git-ignored — never commit it.
>
> ⚠️ `DB_PATH=users.db` is **local dev only**. In Docker/Coolify the path is hardcoded to `/app/data/bot.db` — never set `DB_PATH` in production.

### 4. Run the Bot

```bash
python main.py
```

## Commands

All responses are **ephemeral** (only visible to the user who invoked the command).

| Command        | Description                                                              |
| -------------- | ------------------------------------------------------------------------ |
| `/help`        | Show all available commands with interactive buttons                     |
| `/usage`       | View your LiteLLM usage stats (first time: prompts for your virtual key) |
| `/models`      | List all models you have access to (first time: prompts for your virtual key) |
| `/reset-key`   | Replace your registered virtual key                                      |
| `/delete-key`  | Delete your virtual key and all data from the bot                        |

## `/help` Command

The `/help` command displays an embed listing all available commands, along with **interactive buttons** that let you trigger each command directly without typing:

| Button           | Action                                                     |
| ---------------- | ---------------------------------------------------------- |
| **📊 Usage Stats**   | Runs `/usage` to check your LiteLLM usage statistics       |
| **🤖 Models**        | Runs `/models` to list all accessible AI models            |
| **🔑 Reset Key**     | Opens a modal to reset/update your virtual key             |
| **🗑️ Delete Key**    | Deletes your registered virtual key and data from the bot  |

> The buttons remain interactive for 120 seconds after the `/help` response is sent.

## `/models` Command

The `/models` command displays the models accessible with your virtual key, grouped by provider (e.g., `openai`, `anthropic`, `google`). If the list is too long for a single embed, it shows a summary with model counts per provider.

## Embed Fields

The `/usage` command displays a rich embed with the following fields:

| Field            | Description                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| **🔑 Virtual Key**   | Truncated virtual key (last 8 chars)                                       |
| **🏷️ Key Alias**    | Key alias (if set in LiteLLM proxy)                                        |
| **💰 Total Spend**   | Spend in USD + converted THB (live exchange rate from [exchangerate API](https://www.exchangerate-api.com)) |
| **📅 Expires**       | Key expiration date                                                        |
| **🕐 Last Active**   | Last API call time (converted to Asia/Bangkok timezone)                    |
| **⚡ Rate Limits**    | RPM, TPM, and max parallel requests limits                                 |
| **💵 Max Budget**    | Per-key budget cap (if configured)                                         |
| **🤖 Models**        | Allowed models (or "All models")                                           |
| **⚙️ Config**        | Additional key configuration (if any)                                      |

## How It Works

1. **First run** — User types `/usage` or `/models` → bot opens a modal asking for their virtual key → key is saved to SQLite → data is fetched and displayed as a rich embed.
2. **Subsequent runs** — `/usage` or `/models` looks up the stored key and fetches data immediately.
3. **`/reset-key`** — Opens a modal to replace the stored virtual key.
4. **`/delete-key`** — Permanently deletes the user's virtual key and all associated data from the bot's database.

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
├── main.py              # Bot source code
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker image (hardcoded DB at /app/data/bot.db)
├── docker-compose.yml   # Docker Compose (named volume: bot-data → /app/data)
├── .dockerignore        # Excluded from Docker build context
├── .env                 # Secrets (git-ignored)
├── .env.example         # Template for .env
├── .gitignore           # Git exclusions
├── CHANGELOG.md         # Version history
├── users.db             # SQLite database (local dev only, git-ignored)
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
| `LITELLM_BASE_URL` | No       | `https://litellm.sam.co.th` |

4. Coolify will build and deploy the bot. Database is persisted via a **named Docker volume** (`bot-data` → `/app/data`) and survives redeployments automatically.

> **⚠️ Important:** The database path is hardcoded to `/app/data/bot.db`. Do **not** set `DB_PATH` in Coolify environment variables — it will cause data loss if the path differs from the volume mount.

### Healthcheck

The Dockerfile includes a built-in healthcheck:

```
Interval: 60s | Timeout: 10s | Start period: 30s | Retries: 3
```

The check verifies:
1. The `python` process is running
2. The database file (`/app/data/bot.db`) exists — confirming the bot has initialized successfully

If the container becomes **unhealthy**, Coolify/Docker will automatically restart it.

### Local Docker

```bash
cp .env.example .env
# Fill in BOT_TOKEN, MASTER_KEY, and LITELLM_BASE_URL
# For local Docker: DO NOT set DB_PATH (use the default /app/data/bot.db)
docker compose up --build -d
```

## Tech Stack

| Component       | Technology                                    |
| --------------- | --------------------------------------------- |
| Runtime         | Python 3.12+                                  |
| Discord Library | discord.py 2.x                                |
| HTTP Client     | aiohttp (async HTTP requests)                 |
| Database        | SQLite (per-user virtual key storage)         |
| Config          | python-dotenv (environment variable loading)  |
| Timezone        | tzdata (Asia/Bangkok timezone support)        |
| Containerization| Docker + Docker Compose                       |
