import os

from dotenv import load_dotenv
import sqlite3
import aiohttp
import discord
from discord.ext.commands import Bot as CommandsBot
from datetime import datetime, timezone

load_dotenv()

# ── Configuration ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MASTER_KEY = os.getenv("MASTER_KEY", "")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.sam.co.th/v1")
DB_PATH = os.getenv("DB_PATH", "users.db")

# ── Database ─────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     TEXT PRIMARY KEY,
            virtual_key TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_user_key(user_id: str):
    conn = get_db()
    row = conn.execute(
        "SELECT virtual_key FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["virtual_key"] if row else None


def save_user_key(user_id: str, virtual_key: str):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute(
        """
        INSERT OR REPLACE INTO users (user_id, virtual_key, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, virtual_key, now, now),
    )
    conn.commit()
    conn.close()


# ── LiteLLM API ──────────────────────────────────────────────────
async def fetch_usage(virtual_key: str) -> dict:
    url = f"{LITELLM_BASE_URL}/key/info"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            params={"key": virtual_key},
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


def _truncate_key(key: str) -> str:
    return f"****{key[-8:]}" if len(key) > 8 else key


def format_usage_embed(data: dict) -> discord.Embed:
    key = data.get("key", "N/A")
    info = data.get("info", {})

    spend = info.get("spend", 0.0)
    models = info.get("models", [])
    expires = info.get("expires", "N/A")
    aliases = info.get("aliases", {})
    config = info.get("config", {})
    max_budget = info.get("max_budget", None)
    key_name = info.get("key_name", "N/A")

    embed = discord.Embed(
        title="📊 LiteLLM Usage Report",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=key_name)
    embed.add_field(name="🔑 Virtual Key", value=f"```{_truncate_key(key)}```", inline=True)
    embed.add_field(name="💰 Total Spend", value=f"${spend:,.6f} USD", inline=True)
    embed.add_field(name="📅 Expires", value=str(expires), inline=True)

    if max_budget is not None:
        embed.add_field(name="💵 Max Budget", value=f"${max_budget:,.2f}", inline=True)

    models_str = ", ".join(models) if models else "All models"
    embed.add_field(name="🤖 Models", value=models_str, inline=True)

    if aliases:
        alias_str = "\n".join(f"{k} → {v}" for k, v in aliases.items())
        embed.add_field(name="🏷️ Aliases", value=f"```{alias_str}```", inline=False)

    if config:
        config_str = "\n".join(f"{k}: {v}" for k, v in config.items())
        embed.add_field(name="⚙️ Config", value=f"```{config_str}```", inline=False)

    return embed


# ── Modals ──────────────────────────────────────────────────────
class UsageKeyModal(discord.ui.Modal, title="🔑 First-Time Setup — Enter Virtual Key"):
    key_input = discord.ui.TextInput(
        label="LiteLLM Virtual Key",
        placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
        style=discord.TextStyle.short,
        required=True,
        min_length=1,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        virtual_key = self.key_input.value
        save_user_key(user_id, virtual_key)

        await interaction.response.send_message(
            "✅ Virtual key saved! Fetching usage data ...", ephemeral=False
        )

        try:
            data = await fetch_usage(virtual_key)
            embed = format_usage_embed(data)
            embed.set_footer(text=f"Requested by {interaction.user}")
            await interaction.followup.send(embed=embed)
        except aiohttp.ClientResponseError as e:
            status = e.status
            if status == 401:
                msg = (
                    "🔐 **Authentication failed.** Your virtual key may be invalid or expired.\n"
                    "Use **`/reset-token`** to update your key."
                )
            elif status == 404:
                msg = (
                    "❌ Key not found. The virtual key may have been deleted.\n"
                    "Use **`/reset-token`** to register a new key."
                )
            else:
                msg = (
                    f"❌ Error fetching usage data (HTTP {status}).\n"
                    "Use **`/reset-token`** to update your key."
                )
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Unexpected error: `{type(e).__name__}`", ephemeral=True
            )


class ResetKeyModal(discord.ui.Modal, title="🔑 Reset Virtual Key"):
    key_input = discord.ui.TextInput(
        label="New LiteLLM Virtual Key",
        placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
        style=discord.TextStyle.short,
        required=True,
        min_length=1,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        save_user_key(user_id, self.key_input.value)
        await interaction.response.send_message(
            "✅ Virtual key updated successfully!", ephemeral=True
        )


# ── Bot ──────────────────────────────────────────────────────────
class LiteLLMBot(CommandsBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_db()
        await self.tree.sync()
        print("✅ Database initialized")
        print("✅ Commands synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")


bot = LiteLLMBot()


# ── /usage ───────────────────────────────────────────────────────
@bot.tree.command(
    name="usage",
    description="Check your LiteLLM usage statistics",
)
async def usage(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    virtual_key = get_user_key(user_id)

    # First time? Prompt for key via modal.
    if virtual_key is None:
        await interaction.response.send_modal(UsageKeyModal())
        return

    # Known user — defer and fetch.
    await interaction.response.defer()

    try:
        data = await fetch_usage(virtual_key)
        embed = format_usage_embed(data)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed)
    except aiohttp.ClientResponseError as e:
        status = e.status
        if status == 401:
            msg = (
                "🔐 **Authentication failed.** Your virtual key may be invalid or expired.\n"
                "Use **`/reset-token`** to update your key."
            )
        elif status == 404:
            msg = (
                "❌ Key not found. The virtual key may have been deleted.\n"
                "Use **`/reset-token`** to register a new key."
            )
        else:
            msg = (
                f"❌ Error fetching usage data (HTTP {status}).\n"
                "Use **`/reset-token`** to update your key."
            )
        await interaction.followup.send(msg, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            f"❌ Unexpected error: `{type(e).__name__}`", ephemeral=True
        )


# ── /reset-token ─────────────────────────────────────────────────
@bot.tree.command(
    name="reset-token",
    description="Reset your LiteLLM virtual key",
)
async def reset_token(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    existing = get_user_key(user_id)

    if existing is None:
        await interaction.response.send_message(
            "⚠️ You don't have a registered virtual key yet.\n"
            "Use **`/usage`** to set one up first.",
            ephemeral=True,
        )
        return

    await interaction.response.send_modal(ResetKeyModal())


# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
