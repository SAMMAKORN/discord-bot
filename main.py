"""LiteLLM Usage Discord Bot — Entry Point."""

import os
import sys

# Force UTF-8 stdout on Windows (cp874 can't print emojis)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from bot import api, commands  # noqa: E402
from bot import db  # noqa: E402

# ── Configuration ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MASTER_KEY = os.getenv("MASTER_KEY", "")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.sam.co.th")
DB_PATH = os.getenv("DB_PATH", "/app/data/bot.db")

# Initialize module configs
api.configure(LITELLM_BASE_URL, MASTER_KEY)
db.configure(DB_PATH)

# ── Bot ──────────────────────────────────────────────────────────
bot = commands.LiteLLMBot()
commands.register_commands(bot)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
