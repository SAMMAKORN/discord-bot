"""Discord command handlers, buttons, modals, and views."""

import asyncio
import traceback
from datetime import datetime, timezone

import aiohttp
import discord
from discord import errors as discord_errors
from discord.ext.commands import Bot as CommandsBot

from . import api, db, embeds


# ── Interaction Helpers ────────────────────────────────────────
async def safe_send(interaction: discord.Interaction, **kwargs):
    """Send a message using followup if response is already done."""
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def safe_send_modal(interaction: discord.Interaction, modal: discord.ui.Modal):
    """Send a modal using followup if response is already done."""
    if interaction.response.is_done():
        await interaction.followup.send_modal(modal)
    else:
        await interaction.response.send_modal(modal)


async def _handle_interaction_error(interaction: discord.Interaction, error: Exception, context: str = "command"):
    """Defer or respond to an interaction when an unhandled exception occurs.

    Discord requires a response within 3 seconds — this ensures we always respond.
    """
    # Ignore "Unknown interaction" — the interaction expired, nothing we can do
    if isinstance(error, discord_errors.NotFound) and getattr(error, 'code', None) == 10062:
        print(f"[{context}] Interaction expired (10062) — ignoring")
        return
    if isinstance(error, discord_errors.HTTPException) and getattr(error, 'code', None) == 40060:
        print(f"[{context}] Interaction already acknowledged (40060) — ignoring")
        return

    print(f"[{context}] ERROR: {type(error).__name__}: {error}")
    traceback.print_exc()

    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Something went wrong. Please try again later.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Something went wrong. Please try again later.", ephemeral=True
            )
    except (discord_errors.NotFound, discord_errors.HTTPException) as e:
        # Interaction expired or already acknowledged — nothing we can do
        print(f"[{context}] Failed to send error response (interaction expired): {e}")
    except Exception as e:
        print(f"[{context}] Failed to send error response: {e}")


# ── Shared Follow-up Helpers ───────────────────────────────────
async def _send_usage_followup(interaction: discord.Interaction, virtual_key: str):
    """Fetch usage data and send it as a follow-up embed."""
    try:
        data = await api.fetch_usage(virtual_key)
        emb = await embeds.format_usage_embed(data)
        emb.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=emb, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(embeds._error_message(e.status, "usage data"), ephemeral=True)
    except Exception:
        await interaction.followup.send(
            "❌ Something went wrong. Please try again later.", ephemeral=True
        )


async def _send_models_followup(interaction: discord.Interaction, virtual_key: str):
    """Fetch accessible model list + model info and send as embed."""
    try:
        models_resp, pricing_lookup = await asyncio.gather(
            api.fetch_models(virtual_key),
            api.fetch_model_info_all(),
        )
        print(f"[models] /v1/models: {len(models_resp.get('data', []))} models")
        print(f"[models] /model/info: {len(pricing_lookup)} model configs")

        emb = embeds.format_models_info_embed(models_resp, pricing_lookup)
        print(f"[models] embed built: {len(emb.fields)} fields")
        emb.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=emb, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        print(f"[models] HTTP error {e.status}: {e.message}")
        await interaction.followup.send(embeds._error_message(e.status, "model info"), ephemeral=True)
    except Exception as e:
        print(f"[models] Exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        await interaction.followup.send(
            "❌ Something went wrong. Please try again later.", ephemeral=True
        )


async def _send_usage_daily_followup(interaction: discord.Interaction, virtual_key: str):
    """Fetch today's usage dashboard and send it as a follow-up embed."""
    try:
        key_data, team_list = await asyncio.gather(
            api.fetch_usage(virtual_key),
            api.fetch_team_list(),
        )
        team_info = embeds._resolve_team_info(team_list, key_data)
        if team_info is None or not team_info["team_id"]:
            await interaction.followup.send(
                "❌ Could not find your team.", ephemeral=True,
            )
            return

        activity = await api.fetch_team_daily_activity(team_info["team_id"])
        emb = await embeds.format_token_usage_embed(team_info, activity)
        emb.set_footer(text=f"Requested by {interaction.user}")
        await interaction.followup.send(embed=emb, ephemeral=True)
    except aiohttp.ClientResponseError as e:
        await interaction.followup.send(
            embeds._error_message(e.status, "team usage data"), ephemeral=True
        )
    except Exception:
        await interaction.followup.send(
            "❌ Something went wrong. Please try again later.", ephemeral=True
        )


# ── Command Handlers ───────────────────────────────────────────
async def handle_usage(interaction: discord.Interaction):
    """Core logic for /usage — callable from slash command or button."""
    try:
        user_id = str(interaction.user.id)
        virtual_key = await db.get_user_key(user_id)

        if virtual_key is None:
            await safe_send_modal(interaction, KeySetupModal(action="usage"))
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await _send_usage_followup(interaction, virtual_key)
    except Exception as e:
        await _handle_interaction_error(interaction, e, "usage")


async def handle_models(interaction: discord.Interaction):
    """Core logic for /models — callable from slash command or button."""
    try:
        user_id = str(interaction.user.id)
        virtual_key = await db.get_user_key(user_id)

        if virtual_key is None:
            await safe_send_modal(interaction, KeySetupModal(action="models"))
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await _send_models_followup(interaction, virtual_key)
    except Exception as e:
        await _handle_interaction_error(interaction, e, "models")


async def handle_usage_daily(interaction: discord.Interaction):
    """Core logic for /usage-daily — today's usage dashboard."""
    try:
        user_id = str(interaction.user.id)
        virtual_key = await db.get_user_key(user_id)

        if virtual_key is None:
            await safe_send_modal(interaction, KeySetupModal(action="usage-daily"))
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await _send_usage_daily_followup(interaction, virtual_key)
    except Exception as e:
        await _handle_interaction_error(interaction, e, "usage-daily")


async def handle_reset_key(interaction: discord.Interaction):
    """Core logic for /reset-key — callable from slash command or button."""
    try:
        user_id = str(interaction.user.id)
        existing = await db.get_user_key(user_id)

        if existing is None:
            msg = ("⚠️ You don't have a registered virtual key yet.\n"
                   "Use **`/usage`** to set one up first.")
            await safe_send(interaction, content=msg, ephemeral=True)
            return

        await safe_send_modal(interaction, ResetKeyModal())
    except Exception as e:
        await _handle_interaction_error(interaction, e, "reset-key")


async def handle_delete_key(interaction: discord.Interaction):
    """Core logic for /delete-key — shows confirmation view."""
    try:
        user_id = str(interaction.user.id)
        existing = await db.get_user_key(user_id)

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
    except Exception as e:
        await _handle_interaction_error(interaction, e, "delete-key")


# ── Buttons / Views ────────────────────────────────────────────
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


# ── Delete Confirmation ────────────────────────────────────────
class _DeleteConfirmBtn(discord.ui.Button):
    def __init__(self, user_id: str):
        super().__init__(label="Yes, Delete", style=discord.ButtonStyle.danger,
                         custom_id="delete_confirm_yes")
        self._user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        try:
            deleted = await db.delete_user_key(self._user_id)
            msg = "✅ Your data has been deleted successfully." if deleted \
                  else "❌ Failed to delete your data. Please try again."
            await interaction.response.send_message(msg, ephemeral=True)
            self.view.stop()
        except Exception as e:
            print(f"[delete-yes] ERROR: {type(e).__name__}: {e}")
            try:
                await interaction.response.send_message(
                    "❌ Failed to delete. Please try again.", ephemeral=True
                )
            except Exception:
                pass
            self.view.stop()


class _DeleteCancelBtn(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary,
                         custom_id="delete_confirm_no")

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message("✅ Cancelled. Your data is safe.", ephemeral=True)
            self.view.stop()
        except Exception as e:
            print(f"[delete-cancel] ERROR: {e}")
            self.view.stop()


class DeleteConfirmView(discord.ui.View):
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.add_item(_DeleteConfirmBtn(user_id))
        self.add_item(_DeleteCancelBtn())


# ── Modals ─────────────────────────────────────────────────────
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
        try:
            user_id = str(interaction.user.id)
            virtual_key = self.key_input.value
            await db.save_user_key(user_id, virtual_key)

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
        except Exception as e:
            print(f"[modal-setup] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Failed to save key. Please try again.", ephemeral=True
                    )
            except Exception:
                pass


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
        try:
            user_id = str(interaction.user.id)
            await db.save_user_key(user_id, self.key_input.value)
            await interaction.response.send_message(
                "✅ Virtual key updated successfully!", ephemeral=True
            )
        except Exception as e:
            print(f"[modal-reset] ERROR: {type(e).__name__}: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Failed to update key. Please try again.", ephemeral=True
                    )
            except Exception:
                pass


# ── Bot Class ──────────────────────────────────────────────────
class LiteLLMBot(CommandsBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.init_db()
        await self.tree.sync()
        print("✅ Database initialized")
        print("✅ Commands synced")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")

    async def on_command_error(self, ctx, error):
        print(f"[error] Command error: {type(error).__name__}: {error}")

    async def on_application_command_error(self, interaction: discord.Interaction, error):
        """Catch errors from slash commands before they time out Discord."""
        if isinstance(error, discord_errors.NotFound) and getattr(error, 'code', None) == 10062:
            return  # Interaction expired, ignore
        if isinstance(error, discord_errors.HTTPException) and getattr(error, 'code', None) == 40060:
            return  # Already acknowledged, ignore

        print(f"[error] Slash command error: {type(error).__name__}: {error}")
        traceback.print_exc()
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Something went wrong. Please try again later.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ Something went wrong. Please try again later.", ephemeral=True
                )
        except (discord_errors.NotFound, discord_errors.HTTPException) as e:
            print(f"[error] Failed to send error response (interaction expired): {e}")
        except Exception as e:
            print(f"[error] Failed to send error response: {e}")

    async def close(self):
        await api.close_session()
        await db.close_db()
        await super().close()


# ── Slash Commands ─────────────────────────────────────────────
def register_commands(bot: LiteLLMBot):
    """Register all slash commands on the bot instance."""

    @bot.tree.command(name="usage", description="Check your LiteLLM usage statistics")
    async def usage(interaction: discord.Interaction):
        await handle_usage(interaction)

    @bot.tree.command(name="models", description="List all models you have access to")
    async def models(interaction: discord.Interaction):
        await handle_models(interaction)

    @bot.tree.command(name="reset-key", description="Reset your LiteLLM virtual key")
    async def reset_key(interaction: discord.Interaction):
        await handle_reset_key(interaction)

    @bot.tree.command(name="delete-key", description="Delete your data from the system")
    async def delete_key(interaction: discord.Interaction):
        await handle_delete_key(interaction)

    @bot.tree.command(name="usage-daily", description="Check today's usage dashboard (spend, tokens, requests)")
    async def usage_daily(interaction: discord.Interaction):
        await handle_usage_daily(interaction)

    @bot.tree.command(name="help", description="Show all available commands with interactive buttons")
    async def help_command(interaction: discord.Interaction):
        try:
            emb = embeds.build_help_embed(interaction.user)
            await interaction.response.send_message(embed=emb, view=HelpView(), ephemeral=True)
        except Exception as e:
            await _handle_interaction_error(interaction, e, "help")
