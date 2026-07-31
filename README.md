# LiteLLM Usage Discord Bot

A Discord bot for checking LiteLLM proxy usage via the `/usage` slash command. Users register their virtual key on first use, and the bot queries the LiteLLM proxy API to display spend, models, expiry, and more.

## Requirements

- Python 3.10+
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
LITELLM_BASE_URL=https://litellm.sam.co.th/v1
DB_PATH=users.db
```

> ⚠️ `.env` is git-ignored — never commit it.

### 4. Run the Bot

```bash
python main.py
```

## Commands

| Command | Description |
|---|---|
| `/usage` | View your LiteLLM usage stats (first time: prompts for your virtual key) |
| `/reset-token` | Replace your registered virtual key |

## How It Works

1. **First run** — User types `/usage` → bot opens a modal asking for their virtual key → key is saved to SQLite (`users.db`) → usage data is fetched and displayed as a rich embed.
2. **Subsequent runs** — `/usage` looks up the stored key and fetches usage data immediately.
3. **`/reset-token`** — Opens a modal to replace the stored virtual key.

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
├── main.py            # Bot source code
├── requirements.txt   # Python dependencies
├── .env               # Secrets (git-ignored)
├── .env.example       # Template for .env
├── .gitignore
├── users.db           # SQLite database (auto-created, git-ignored)
└── README.md
```
