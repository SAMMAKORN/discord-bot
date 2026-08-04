import asyncio
import os

from dotenv import load_dotenv
import sqlite3
import aiohttp
import discord
from discord.ext.commands import Bot as CommandsBot
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

load_dotenv()

# ── Configuration ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MASTER_KEY = os.getenv("MASTER_KEY", "")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.sam.co.th")
DB_PATH = os.getenv("DB_PATH", "/app/data/bot.db")

# ── Database ─────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    """Return a new SQLite connection with Row factory enabled."""
    db_path = Path(DB_PATH)

    # SQLite can create the database file
    # but won't create the parent directory
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the users table if it does not already exist."""
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


def get_user_key(user_id: str) -> str | None:
    """Return the stored virtual key for *user_id*, or ``None``."""
    conn = get_db()
    row = conn.execute(
        "SELECT virtual_key FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["virtual_key"] if row else None


def save_user_key(user_id: str, virtual_key: str):
    """Insert or update the virtual key for *user_id*."""
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


def delete_user_key(user_id: str) -> bool:
    """Delete the user's virtual key; return ``True`` if a row was removed."""
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM users WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


# ── LiteLLM API ──────────────────────────────────────────────────
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def fetch_usage(virtual_key: str) -> dict:
    """GET /key/info — returns key metadata and spend."""
    url = f"{LITELLM_BASE_URL}/key/info"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            params={"key": virtual_key},
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
            timeout=_HTTP_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def fetch_models(virtual_key: str) -> dict:
    """GET /v1/models — returns accessible model list."""
    url = f"{LITELLM_BASE_URL}/v1/models"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {virtual_key}"},
            timeout=_HTTP_TIMEOUT,
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
    """Mask the leading characters of *key*, keeping only the last 8."""
    return f"****{key[-8:]}" if len(key) > 8 else key


# ── Team API helpers ─────────────────────────────────────────────
async def fetch_team_list() -> list[dict]:
    """GET /team/list — returns all teams managed by the proxy."""
    url = f"{LITELLM_BASE_URL}/team/list"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
            timeout=_HTTP_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, list) else data.get("data", [])


async def fetch_team_daily_activity(team_id: str) -> dict:
    """GET /team/daily/activity — today only."""
    today = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d")
    url = f"{LITELLM_BASE_URL}/team/daily/activity"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            params={"team_id": team_id, "start_date": today, "end_date": today, "page": 1},
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
            timeout=_HTTP_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


def _extract_key_metrics(results: list[dict], key_alias: str) -> tuple[dict, bool]:
    """Sum metrics for a specific key_alias across results.

    Returns (totals_dict, was_found) where was_found is True if at least one
    entry matched the alias (exact or suffix fallback).
    """
    totals = {
        "spend": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "api_requests": 0,
    }
    found = False
    alias_suffix = key_alias[-8:] if len(key_alias) > 8 else key_alias
    for day in results:
        api_keys = day.get("breakdown", {}).get("api_keys", {})
        for _khash, kinfo in api_keys.items():
            remote_alias = (kinfo.get("metadata", {}).get("key_alias") or "")
            # Exact match first, then suffix fallback
            if remote_alias == key_alias or remote_alias.endswith(alias_suffix):
                m = kinfo.get("metrics", {})
                for k, v in m.items():
                    if k in totals and isinstance(v, (int, float)):
                        totals[k] += v
                found = True
                break
    return totals, found


def _find_team_for_key(team_list: list[dict], virtual_key: str) -> dict | None:
    key_alias = virtual_key[-8:] if len(virtual_key) > 8 else virtual_key
    for team in team_list:
        for key_info in (team.get("keys") or []):
            token = key_info.get("token", "")
            if token.endswith(key_alias):
                return {
                    "team_alias": team.get("team_alias", "Unknown"),
                    "team_id": team.get("team_id", ""),
                    "key_alias": key_info.get("key_alias", "Unknown"),
                }
    return None


def _resolve_team_info(team_list: list[dict], key_info: dict) -> dict | None:
    info = (key_info or {}).get("info", {}) or {}
    team_id = info.get("team_id")
    if team_id:
        for team in team_list:
            if team.get("team_id") == team_id:
                ka = info.get("key_alias") or info.get("key_name", "Unknown")
                return {
                    "team_alias": team.get("team_alias", "Unknown"),
                    "team_id": team_id,
                    "key_alias": ka,
                }
        return {
            "team_alias": "Unknown",
            "team_id": team_id,
            "key_alias": info.get("key_alias") or info.get("key_name", "Unknown"),
        }
    virtual_key = (key_info or {}).get("key", "")
    return _find_team_for_key(team_list, virtual_key)


def format_token_usage_embed(team_info: dict, activity: dict) -> discord.Embed:
    """Format today's token usage stats for the user's key."""
    team_alias = team_info.get("team_alias", "Unknown")
    key_alias = team_info.get("key_alias", "Unknown")

    results = activity.get("results", [])
    key_metrics, key_found = _extract_key_metrics(results, key_alias)

    total_requests = key_metrics["api_requests"]
    total_successful = key_metrics["successful_requests"]
    total_failed = key_metrics["failed_requests"]
    total_tokens = key_metrics["total_tokens"]
    total_spend = key_metrics["spend"]

    avg_tokens = total_tokens // total_requests if total_requests > 0 else 0
    avg_spend = total_spend / total_requests if total_requests > 0 else 0.0

    now_bkk = datetime.now(ZoneInfo("Asia/Bangkok"))
    today_str = now_bkk.strftime("%Y-%m-%d")

    color = discord.Color.blurple() if key_found else discord.Color.dark_gold()

    embed = discord.Embed(
        title=f"{key_alias} (team: {team_alias})",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Summary Row
    embed.add_field(
        name="\U0001f4ca **Total Requests**",
        value=f"`{total_requests:,}`\n",
        inline=True,
    )
    embed.add_field(
        name="\U0001f999 **Total Tokens**",
        value=f"`{total_tokens:,}`\n",
        inline=True,
    )
    embed.add_field(
        name="\U0001f4b0 **Total Spend**",
        value=f"`${total_spend:,.2f}`\n",
        inline=True,
    )

    # Breakdown Row
    embed.add_field(
        name="\u2705 **Successful**",
        value=f"`{total_successful:,}`",
        inline=True,
    )
    embed.add_field(
        name="\u274c **Failed**",
        value=f"`{total_failed:,}`",
        inline=True,
    )
    embed.add_field(
        name="\u26a1 **Avg/request**",
        value=f"`{avg_tokens:,}` tok\n`${avg_spend:,.4f}`",
        inline=True,
    )

    if not key_found and not results:
        embed.add_field(
            name="\u26a0\ufe0f Note",
            value="No activity data found for today. The dashboard will show zeroes.",
            inline=False,
        )
    elif not key_found:
        embed.add_field(
            name="\u26a0\ufe0f Note",
            value="Could not find your key in today's activity. "
            "Your key alias may differ from the team record.",
            inline=False,
        )

    embed.set_footer(text=f"\U0001f4c5 Today \u2014 {today_str} (Bangkok)")

    return embed


def format_usage_embed(data: dict, usd_thb_rate: float = 0.0) -> discord.Embed:
    data = data or {}
    info = data.get("info") or {}
    key = data.get("key", "N/A")

    spend = info.get("spend", 0.0)
    models = info.get("models", [])
    expires = info.get("expires", "N/A")
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
    models_display = models_str if len(models_str) <= 100 else f"{models_str[:97]}..."
    embed.add_field(name="🤖 Models", value=models_display, inline=True)

    if config:
        config_str = "\n".join(f"{k}: {v}" for k, v in config.items())
        embed.add_field(name="⚙️ Config", value=f"```{config_str}```", inline=False)

    return embed


def format_models_embed(data: dict) -> discord.Embed:
    models = data.get("data", [])
    embed = discord.Embed(
        title="🤖 Available Models",
        description=f"Found **{len(models)}** model(s) you have access to.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    # Group models by provider prefix
    provider_groups = {}
    ungrouped = []
    for m in models:
        id_ = m.get("id", "unknown")
        # Extract provider prefix (e.g., "openai/gpt-4" → "openai")
        if "/" in id_:
            provider = id_.split("/")[0]
        else:
            provider = None

        if provider:
            provider_groups.setdefault(provider, [])
            provider_groups[provider].append(id_)
        else:
            ungrouped.append(id_)

    # Build description by provider
    chunks = []
    for provider, model_ids in sorted(provider_groups.items()):
        models_text = "\n".join(f"• `{m}`" for m in sorted(model_ids))
        chunks.append(f"**{provider}** ({len(model_ids)})\n{models_text}")

    if ungrouped:
        models_text = "\n".join(f"• `{m}`" for m in sorted(ungrouped))
        chunks.append(f"**Other** ({len(ungrouped)})\n{models_text}")

    # Discord embed description limit is 1024 chars; split if needed
    full_text = "\n\n".join(chunks)
    if len(full_text) > 1000:
        # Fallback: show count only with top providers
        summary_parts = []
        for provider, model_ids in sorted(provider_groups.items()):
            summary_parts.append(f"{provider}: {len(model_ids)}")
        if ungrouped:
            summary_parts.append(f"other: {len(ungrouped)}")
        summary = ", ".join(summary_parts[:10])
        if len(summary_parts) > 10:
            summary += " ..."
        full_text = f"⚠️ Too many models to display.\n{summary}"

    embed.add_field(name="Models", value=full_text, inline=False)
    return embed


# ── Interaction helpers ──────────────────────────────────────────
async def safe_send(interaction: discord.Interaction, **kwargs):
    """Send a message using followup if response is already done, else initial response."""
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send(**kwargs)


async def safe_send_modal(interaction: discord.Interaction, modal: discord.ui.Modal):
    """Send a modal using followup if response is already done, else initial response."""
    if interaction.response.is_done():
        await interaction.followup.send_modal(modal)
    else:
        await interaction.response.send_modal(modal)


# ── Shared follow-up helpers ─────────────────────────────────────
async def _send_usage_followup(interaction: discord.Interaction, virtual_key: str):
    """Fetch usage data and send it as a follow-up embed."""
    try:
        data = await fetch_usage(virtual_key)
        rate = await fetch_usd_thb_rate()
        embed = format_usage_embed(data, rate)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(_error_message(e.status, "usage data"), ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "❌ Something went wrong. Please try again later.", ephemeral=True
        )


async def _send_models_followup(interaction: discord.Interaction, virtual_key: str):
    """Fetch available models and send them as a follow-up embed."""
    try:
        data = await fetch_models(virtual_key)
        embed = format_models_embed(data)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(_error_message(e.status, "models"), ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "❌ Something went wrong. Please try again later.", ephemeral=True
        )


async def _send_usage_daily_followup(interaction: discord.Interaction, virtual_key: str):
    """Fetch today's usage dashboard and send it as a follow-up embed."""
    try:
        key_data, team_list = await asyncio.gather(
            fetch_usage(virtual_key),
            fetch_team_list(),
        )
        team_info = _resolve_team_info(team_list, key_data)
        if team_info is None or not team_info["team_id"]:
            await interaction.followup.send(
                "❌ Could not find your team.", ephemeral=True,
            )
            return

        activity = await fetch_team_daily_activity(team_info["team_id"])
        embed = format_token_usage_embed(team_info, activity)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(
            _error_message(e.status, "team usage data"), ephemeral=True
        )
    except Exception:
        await interaction.followup.send(
            "❌ Something went wrong. Please try again later.", ephemeral=True
        )


# ── Command handlers (shared by slash commands and buttons) ──────
async def handle_usage(interaction: discord.Interaction):
    """Core logic for /usage — callable from slash command or button."""
    user_id = str(interaction.user.id)
    virtual_key = get_user_key(user_id)

    if virtual_key is None:
        await safe_send_modal(interaction, KeySetupModal(action="usage"))
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    await _send_usage_followup(interaction, virtual_key)


async def handle_models(interaction: discord.Interaction):
    """Core logic for /models — callable from slash command or button."""
    user_id = str(interaction.user.id)
    virtual_key = get_user_key(user_id)

    if virtual_key is None:
        await safe_send_modal(interaction, KeySetupModal(action="models"))
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    await _send_models_followup(interaction, virtual_key)


async def handle_usage_daily(interaction: discord.Interaction):
    """Core logic for /usage-daily — today's usage dashboard via /team/daily/activity."""
    user_id = str(interaction.user.id)
    virtual_key = get_user_key(user_id)

    if virtual_key is None:
        await safe_send_modal(interaction, KeySetupModal(action="usage-daily"))
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    await _send_usage_daily_followup(interaction, virtual_key)


async def handle_reset_key(interaction: discord.Interaction):
    """Core logic for /reset-key — callable from slash command or button."""
    user_id = str(interaction.user.id)
    existing = get_user_key(user_id)

    if existing is None:
        msg = ("⚠️ You don't have a registered virtual key yet.\n"
               "Use **`/usage`** to set one up first.")
        await safe_send(interaction, content=msg, ephemeral=True)
        return

    await safe_send_modal(interaction, ResetKeyModal())


async def handle_delete_key(interaction: discord.Interaction):
    """Core logic for /delete-key — shows confirmation view."""
    user_id = str(interaction.user.id)
    existing = get_user_key(user_id)

    if existing is None:
        msg = "⚠️ You don't have any registered data to delete."
        await safe_send(interaction, content=msg, ephemeral=True)
        return

    await safe_send(
        interaction,
        content="⚠️ **Are you sure?** This will permanently delete your virtual key and all data.",
        view=DeleteConfirmView(user_id),
        ephemeral=True,
    )


# ── Buttons / Views ──────────────────────────────────────────────
class UsageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Usage Stats", style=discord.ButtonStyle.primary,
                         custom_id="help_usage", emoji="📊", row=0)

    async def callback(self, interaction: discord.Interaction):
        await handle_usage(interaction)


class ModelsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Models", style=discord.ButtonStyle.primary,
                         custom_id="help_models", emoji="🤖", row=0)

    async def callback(self, interaction: discord.Interaction):
        await handle_models(interaction)


class ResetKeyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Reset Key", style=discord.ButtonStyle.secondary,
                         custom_id="help_reset_key", emoji="🔑", row=1)

    async def callback(self, interaction: discord.Interaction):
        await handle_reset_key(interaction)


class DeleteKeyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Delete Key", style=discord.ButtonStyle.danger,
                         custom_id="help_delete_key", emoji="🗑️", row=1)

    async def callback(self, interaction: discord.Interaction):
        await handle_delete_key(interaction)


class UsageDailyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Daily Usage", style=discord.ButtonStyle.primary,
                         custom_id="help_usage_daily", emoji="🪙", row=0)

    async def callback(self, interaction: discord.Interaction):
        await handle_usage_daily(interaction)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(UsageButton())
        self.add_item(UsageDailyButton())
        self.add_item(ModelsButton())
        self.add_item(ResetKeyButton())
        self.add_item(DeleteKeyButton())


# ── Delete confirmation ──────────────────────────────────────────
class _DeleteConfirmBtn(discord.ui.Button):
    def __init__(self, user_id: str):
        super().__init__(label="Yes, Delete", style=discord.ButtonStyle.danger,
                         custom_id="delete_confirm_yes")
        self._user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        deleted = delete_user_key(self._user_id)
        msg = "✅ Your data has been deleted successfully." if deleted \
              else "❌ Failed to delete your data. Please try again."
        await interaction.response.send_message(msg, ephemeral=True)
        self.view.stop()


class _DeleteCancelBtn(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary,
                         custom_id="delete_confirm_no")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Cancelled. Your data is safe.", ephemeral=True)
        self.view.stop()


class DeleteConfirmView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.add_item(_DeleteConfirmBtn(user_id))
        self.add_item(_DeleteCancelBtn())


# ── Modals ──────────────────────────────────────────────────────
class KeySetupModal(discord.ui.Modal, title="🔑 First-Time Setup — Enter Virtual Key"):
    """Unified modal for key setup — handles both /usage and /models flows."""
    def __init__(self, action: str = "usage"):
        super().__init__()
        self._action = action

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

        messages = {
            "usage": "✅ Virtual key saved! Fetching usage data ...",
            "usage-daily": "✅ Virtual key saved! Fetching usage data ...",
        }
        status_msg = messages.get(self._action,
                                  "✅ Virtual key saved! Fetching available models ...")
        await interaction.response.send_message(content=status_msg, ephemeral=True)

        if self._action == "usage":
            await _send_usage_followup(interaction, virtual_key)
        elif self._action == "usage-daily":
            await _send_usage_daily_followup(interaction, virtual_key)
        else:
            await _send_models_followup(interaction, virtual_key)


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


def _error_message(status: int, context: str = "data") -> str:
    """Build a user-friendly error message from HTTP status code."""
    if status == 401:
        return ("🔐 **Authentication failed.** Your virtual key may be invalid or expired.\n"
                "Use **`/reset-key`** to update your key.")
    elif status == 404:
        return ("❌ Key not found. The virtual key may have been deleted.\n"
                "Use **`/reset-key`** to register a new key.")
    else:
        return (f"❌ Error fetching {context} (HTTP {status}).\n"
                "Use **`/reset-key`** to update your key.")


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


# ── Slash Commands (delegate to shared handlers) ─────────────────
@bot.tree.command(
    name="usage",
    description="Check your LiteLLM usage statistics",
)
async def usage(interaction: discord.Interaction):
    await handle_usage(interaction)


@bot.tree.command(
    name="models",
    description="List all models you have access to",
)
async def models(interaction: discord.Interaction):
    await handle_models(interaction)


@bot.tree.command(
    name="reset-key",
    description="Reset your LiteLLM virtual key",
)
async def reset_key(interaction: discord.Interaction):
    await handle_reset_key(interaction)


@bot.tree.command(
    name="delete-key",
    description="Delete your data from the system",
)
async def delete_key(interaction: discord.Interaction):
    await handle_delete_key(interaction)


@bot.tree.command(
    name="usage-daily",
    description="Check today's usage dashboard (spend, tokens, requests)",
)
async def usage_daily(interaction: discord.Interaction):
    await handle_usage_daily(interaction)


# ── /help ────────────────────────────────────────────────────────
@bot.tree.command(
    name="help",
    description="Show all available commands with interactive buttons",
)
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 LiteLLM Bot — Commands",
        description=(
            "Here are all available commands. **Click a button below** to run each "
            "command directly, or type the slash command in chat!"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Requested by {interaction.user}")

    # Command details as fields
    embed.add_field(
        name="`/usage`",
        value="📊 Check your LiteLLM usage statistics (spend, models, rate limits, etc.)",
        inline=False,
    )
    embed.add_field(
        name="`/usage-daily`",
        value="🪙 Check today's usage dashboard (spend, tokens, requests)",
        inline=False,
    )
    embed.add_field(
        name="`/models`",
        value="🤖 List all AI models you have access to",
        inline=False,
    )
    embed.add_field(
        name="`/reset-key`",
        value="🔑 Reset / update your LiteLLM virtual key",
        inline=False,
    )
    embed.add_field(
        name="`/delete-key`",
        value="🗑️ Delete your data from the system",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)


# ── Main ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
