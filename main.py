"""LiteLLM Usage Discord Bot — Entry Point."""

import logging
import os
import sys

# Force UTF-8 stdout on Windows (cp874 can't print emojis)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from bot import api, commands, db

# ── Configuration ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MASTER_KEY = os.getenv("MASTER_KEY", "")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.sam.co.th")
DB_PATH = os.getenv("DB_PATH", "users.db")

# Initialize module configs
api.configure(LITELLM_BASE_URL, MASTER_KEY)
db.configure(DB_PATH)

# ── Bot ──────────────────────────────────────────────────────────
bot = commands.LiteLLMBot()
commands.register_commands(bot)


def validate_configuration() -> None:
    """Fail fast with actionable errors for required settings."""
    missing = [
        name for name, value in (("BOT_TOKEN", BOT_TOKEN), ("MASTER_KEY", MASTER_KEY)) if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
    if not LITELLM_BASE_URL.startswith(("https://", "http://")):
        raise RuntimeError("LITELLM_BASE_URL must be an absolute HTTP(S) URL")


if __name__ == "__main__":
    validate_configuration()
    bot.run(BOT_TOKEN)
