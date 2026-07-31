import os

from dotenv import load_dotenv
import sqlite3
import aiohttp
import discord
from discord.ext.commands import Bot as CommandsBot
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

load_dotenv()

# ── Configuration ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MASTER_KEY = os.getenv("MASTER_KEY", "")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.sam.co.th")
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


async def fetch_usd_thb_rate() -> float:
    """Fetch live USD/THB exchange rate from exchangerate API (no API key needed)."""
    url = "https://open.er-api.com/v6/latest/USD"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            rate = data.get("rates", {}).get("THB", 0.0)
            return float(rate) if rate else 0.0


def _truncate_key(key: str) -> str:
    return f"****{key[-8:]}" if len(key) > 8 else key


def format_usage_embed(data: dict, usd_thb_rate: float = 0.0) -> discord.Embed:
    key = data.get("key", "N/A")
    info = data.get("info", {})

    spend = info.get("spend", 0.0)
    models = info.get("models", [])
    expires = info.get("expires", "N/A")
    aliases = info.get("aliases", {})
    config = info.get("config", {})
    max_budget = info.get("max_budget", None)
    key_name = info.get("key_name", "N/A")
    key_alias = info.get("key_alias", data.get("key_alias", None))
    last_active = info.get("last_active", None)

    # Rate limits
    rpm_limit = info.get("rpm_requests", None)
    tpm_limit = info.get("tpm_limit", None)
    max_parallel_requests = info.get("max_parallel_requests", None)

    if usd_thb_rate and spend:
        thb = spend * usd_thb_rate
        spend_str = f"${spend:,.2f} USD\n฿{thb:,.2f} THB (1 USD = {usd_thb_rate:,.2f} THB)"
    else:
        spend_str = f"${spend:,.2f} USD"

    embed = discord.Embed(
        title="📊 LiteLLM Usage Report",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=key_name)
    embed.add_field(name="🔑 Virtual Key", value=f"```{_truncate_key(key)}```", inline=True)

    # Key Alias
    if key_alias:
        embed.add_field(name="🏷️ Key Alias", value=key_alias, inline=True)

    embed.add_field(name="💰 Total Spend", value=spend_str, inline=False)
    embed.add_field(name="📅 Expires", value=str(expires), inline=True)

    # Last Active
    if last_active:
        try:
            la_dt = datetime.fromisoformat(str(last_active).replace("Z", "+00:00"))
            la_bkk = la_dt.astimezone(ZoneInfo("Asia/Bangkok"))
            hour = la_bkk.strftime("%I").lstrip("0") or "12"
            la_str = f"{la_bkk:%b %d, %Y} at {hour}:{la_bkk:%M} {la_bkk:%p}"
        except Exception:
            la_str = str(last_active)
        embed.add_field(name="🕐 Last Active", value=la_str, inline=True)

    # Rate Limits
    rate_parts = []
    if rpm_limit is not None:
        rate_parts.append(f"{rpm_limit:,} req/min")
    if tpm_limit is not None:
        rate_parts.append(f"{tpm_limit:,} tok/min")
    if max_parallel_requests is not None:
        rate_parts.append(f"{max_parallel_requests:,} parallel")
    if rate_parts:
        embed.add_field(name="⚡ Rate Limits", value=", ".join(rate_parts), inline=True)

    if max_budget is not None:
        embed.add_field(name="💵 Max Budget", value=f"${max_budget:,.2f}", inline=True)

    models_str = ", ".join(models) if models else "All models"
    embed.add_field(name="🤖 Models", value=models_str, inline=True)

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
            "✅ Virtual key saved! Fetching usage data ...", ephemeral=True
        )

        try:
            data = await fetch_usage(virtual_key)
            rate = await fetch_usd_thb_rate()
            embed = format_usage_embed(data, rate)
            embed.set_footer(text=f"Requested by {interaction.user}")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except aiohttp.ClientResponseError as e:
            status = e.status
            if status == 401:
                msg = (
                    "🔐 **Authentication failed.** Your virtual key may be invalid or expired.\n"
                    "Use **`/reset-key`** to update your key."
                )
            elif status == 404:
                msg = (
                    "❌ Key not found. The virtual key may have been deleted.\n"
                    "Use **`/reset-key`** to register a new key."
                )
            else:
                msg = (
                    f"❌ Error fetching usage data (HTTP {status}).\n"
                    "Use **`/reset-key`** to update your key."
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
    await interaction.response.defer(ephemeral=True)

    try:
        data = await fetch_usage(virtual_key)
        rate = await fetch_usd_thb_rate()
        embed = format_usage_embed(data, rate)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        status = e.status
        if status == 401:
            msg = (
                "🔐 **Authentication failed.** Your virtual key may be invalid or expired.\n"
                "Use **`/reset-key`** to update your key."
            )
        elif status == 404:
            msg = (
                "❌ Key not found. The virtual key may have been deleted.\n"
                "Use **`/reset-key`** to register a new key."
            )
        else:
            msg = (
                f"❌ Error fetching usage data (HTTP {status}).\n"
                "Use **`/reset-key`** to update your key."
            )
        await interaction.followup.send(msg, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            f"❌ Unexpected error: `{type(e).__name__}`", ephemeral=True
        )


# ── /reset-key ──────────────────────────────────────────────────
@bot.tree.command(
    name="reset-key",
    description="Reset your LiteLLM virtual key",
)
async def reset_key(interaction: discord.Interaction):
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
