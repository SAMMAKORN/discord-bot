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
# Database path is FIXED — do not make configurable via env var.
# A mismatched DB_PATH causes data loss on every deploy (file written
# outside the named volume at /app/data). Local dev uses .env to
# override; Docker always uses /app/data/bot.db.
DB_PATH = os.getenv("DB_PATH", "/app/data/bot.db")

# ── Database ─────────────────────────────────────────────────────
def get_db():
    db_path = Path(DB_PATH)

    # SQLite สร้างไฟล์ฐานข้อมูลได้
    # แต่จะไม่สร้างโฟลเดอร์แม่ให้
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
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


def delete_user_key(user_id: str) -> bool:
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


def _get_provider(model_id: str) -> str | None:
    """Extract provider prefix from a model ID (e.g., 'openai/gpt-4' → 'openai')."""
    return model_id.split("/")[0] if "/" in model_id else None


def _format_model_info(m: dict) -> str:
    """Format a single model's token, cost, and capability details."""
    id_ = m.get("id", "unknown")

    # Try nested info/metadata first (LiteLLM /v1/models may include these)
    info = m.get("info", {}) or m.get("metadata", {})
    if not info and isinstance(m.get("root"), dict):
        root = m["root"]
        info = root.get("info", {}) or root.get("metadata", {})

    # Fallback: read top-level keys directly
    if not info:
        info = {k: v for k, v in m.items()
                if k not in ("id", "object", "created", "owned_by", "permission", "root")}

    if not info:
        return f"`{id_}`"

    parts = [f"**`{id_}`**"]

    # ── Token info ───────────────────────────────────────────────
    context = (
        info.get("max_input_tokens")
        or info.get("max_tokens")
        or info.get("max_tokens_request")
        or info.get("max_position_embeddings")
        or info.get("context_window")
    )
    if context:
        parts.append(f"📏 Context: {int(context):,} tokens")

    # ── Capabilities ─────────────────────────────────────────────
    caps = []
    # Vision / Image input
    if info.get("supports_vision") or info.get("vision"):
        caps.append("👁️ Vision")
    elif "image" in [str(x).lower() for x in (info.get("input_modalities") or [])]:
        caps.append("👁️ Vision")

    # Function calling / Tool use
    if info.get("supports_function_calling") or info.get("function_calling"):
        caps.append("🔧 Functions")
    elif info.get("supports_tool_use") or info.get("tool_use"):
        caps.append("🔧 Tools")

    # JSON mode
    if info.get("supports_json_mode") or info.get("json_mode"):
        caps.append("📋 JSON")

    # Image generation
    if info.get("supports_image_generation") or info.get("image_generation"):
        caps.append("🎨 Image Gen")
    elif "image" in [str(x).lower() for x in (info.get("output_modalities") or [])]:
        caps.append("🎨 Image Gen")

    # Modality summary (if no specific caps matched but modalities exist)
    if not caps:
        input_mod = [str(x).lower() for x in (info.get("input_modalities") or [])]
        output_mod = [str(x).lower() for x in (info.get("output_modalities") or [])]
        if input_mod or output_mod:
            caps.append("↔ ".join(input_mod + output_mod))

    if caps:
        parts.append(" | ".join(caps))

    # ── Cost info ────────────────────────────────────────────────
    input_cost = (
        info.get("input_cost_per_token")
        or info.get("input_cost")
        or info.get("input_cost_per_token_cache")
    )
    output_cost = (
        info.get("output_cost_per_token")
        or info.get("output_cost")
    )
    if input_cost is not None or output_cost is not None:
        i_c = f"{float(input_cost or 0):.0f}" if input_cost else "—"
        o_c = f"{float(output_cost or 0):.0f}" if output_cost else "—"
        parts.append(f"💲 ${i_c} in / ${o_c} out (per M tokens)")

    return " — ".join(parts) if len(parts) > 1 else parts[0]


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
        provider = _get_provider(id_)

        if provider:
            provider_groups.setdefault(provider, []).append(m)
        else:
            ungrouped.append(m)

    # Build detailed description by provider
    detailed_chunks = []
    for provider, model_objs in sorted(provider_groups.items()):
        lines = [_format_model_info(m) for m in model_objs]
        detailed_chunks.append(f"**{provider}** ({len(model_objs)})\n" + "\n".join(lines))

    if ungrouped:
        lines = [_format_model_info(m) for m in ungrouped]
        detailed_chunks.append(f"**Other** ({len(ungrouped)})\n" + "\n".join(lines))

    detailed_text = "\n\n".join(detailed_chunks)

    # Discord embed field limit is 1024 chars; fall back to concise list if needed
    if len(detailed_text) > 980:
        concise_chunks = []
        for provider, model_objs in sorted(provider_groups.items()):
            model_ids = [m.get("id", "?") for m in model_objs]
            lines = [_format_model_info(m) for m in model_objs]
            concise_chunks.append(f"**{provider}** ({len(model_ids)})\n" + "\n".join(
                f"• `{mid}`" for mid in sorted(model_ids)
            ))

        if ungrouped:
            model_ids = [m.get("id", "?") for m in ungrouped]
            concise_chunks.append(f"**Other** ({len(model_ids)})\n" + "\n".join(
                f"• `{mid}`" for mid in sorted(model_ids)
            ))

        concise_text = "\n\n".join(concise_chunks)

        if len(concise_text) <= 1000:
            full_text = concise_text
        else:
            # Last resort: provider counts only
            summary_parts = []
            for provider, model_objs in sorted(provider_groups.items()):
                summary_parts.append(f"{provider}: {len(model_objs)}")
            if ungrouped:
                summary_parts.append(f"other: {len(ungrouped)}")
            summary = ", ".join(summary_parts[:10])
            if len(summary_parts) > 10:
                summary += " ..."
            full_text = f"⚠️ Too many models to display.\n{summary}"
    else:
        full_text = detailed_text

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

    try:
        data = await fetch_usage(virtual_key)
        rate = await fetch_usd_thb_rate()
        embed = format_usage_embed(data, rate)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(_error_message(e.status, "usage data"), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            f"❌ Unexpected error: `{type(e).__name__}`", ephemeral=True
        )


async def handle_models(interaction: discord.Interaction):
    """Core logic for /models — callable from slash command or button."""
    user_id = str(interaction.user.id)
    virtual_key = get_user_key(user_id)

    if virtual_key is None:
        await safe_send_modal(interaction, KeySetupModal(action="models"))
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    try:
        data = await fetch_models(virtual_key)
        embed = format_models_embed(data)
        embed.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(_error_message(e.status, "models"), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            f"❌ Unexpected error: `{type(e).__name__}`", ephemeral=True
        )


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

    # Show confirmation buttons
    await safe_send(interaction,
                    content="⚠️ **Are you sure?** This will permanently delete your virtual key and all data.",
                    view=DeleteConfirmView(user_id), ephemeral=True)


# ── Buttons / Views ──────────────────────────────────────────────
class UsageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Usage Stats", style=discord.ButtonStyle.primary,
                         custom_id="help_usage", emoji="📊")

    async def callback(self, interaction: discord.Interaction):
        await handle_usage(interaction)


class ModelsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Models", style=discord.ButtonStyle.primary,
                         custom_id="help_models", emoji="🤖")

    async def callback(self, interaction: discord.Interaction):
        await handle_models(interaction)


class ResetKeyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Reset Key", style=discord.ButtonStyle.secondary,
                         custom_id="help_reset_key", emoji="🔑")

    async def callback(self, interaction: discord.Interaction):
        await handle_reset_key(interaction)


class DeleteKeyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Delete Key", style=discord.ButtonStyle.danger,
                         custom_id="help_delete_key", emoji="🗑️")

    async def callback(self, interaction: discord.Interaction):
        await handle_delete_key(interaction)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(UsageButton())
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

        if self._action == "usage":
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
                await interaction.followup.send(
                    _error_message(e.status, "usage data"), ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Unexpected error: `{type(e).__name__}`", ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "✅ Virtual key saved! Fetching available models ...", ephemeral=True
            )
            try:
                data = await fetch_models(virtual_key)
                embed = format_models_embed(data)
                embed.set_footer(text=f"Requested by {interaction.user}")
                await interaction.followup.send(embed=embed, ephemeral=True)
            except aiohttp.ClientResponseError as e:
                await interaction.followup.send(
                    _error_message(e.status, "models"), ephemeral=True
                )
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
