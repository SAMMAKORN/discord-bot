"""Discord slash commands, modals, and interactive views."""

import logging
import time
from typing import ClassVar
from uuid import uuid4

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands as discord_commands

from . import api, db, embeds

logger = logging.getLogger(__name__)
_RATE_LIMIT_SECONDS = 2.0
_last_action: dict[int, float] = {}


def _is_thai(interaction: discord.Interaction) -> bool:
    locale = getattr(interaction, "locale", None)
    return str(getattr(locale, "value", locale)).lower().startswith("th")


def _text(interaction: discord.Interaction, english: str, thai: str) -> str:
    return thai if _is_thai(interaction) else english


async def safe_send(interaction: discord.Interaction, **kwargs):
    """Send an initial response or follow-up depending on interaction state."""
    if interaction.response.is_done():
        return await interaction.followup.send(**kwargs, wait=True)
    await interaction.response.send_message(**kwargs)
    return await interaction.original_response()


async def safe_send_modal(interaction: discord.Interaction, modal: discord.ui.Modal):
    """Send a modal, which Discord only permits as an initial response."""
    if interaction.response.is_done():
        raise RuntimeError("A modal cannot be sent after an interaction is acknowledged.")
    await interaction.response.send_modal(modal)


async def _check_rate_limit(interaction: discord.Interaction) -> bool:
    now = time.monotonic()
    user_id = interaction.user.id
    last_action = _last_action.get(user_id, 0.0)
    if now - last_action < _RATE_LIMIT_SECONDS:
        await safe_send(
            interaction,
            content=_text(
                interaction,
                "⏳ Please wait a moment before trying another command.",
                "⏳ กรุณารอสักครู่ก่อนเรียกคำสั่งถัดไป",
            ),
            ephemeral=True,
        )
        return False
    _last_action[user_id] = now
    return True


async def _handle_interaction_error(
    interaction: discord.Interaction,
    error: Exception,
    context: str = "command",
):
    """Log an unexpected error and return a traceable user-facing response."""
    if isinstance(error, discord.NotFound) and getattr(error, "code", None) == 10062:
        logger.info("%s interaction expired", context)
        return
    if isinstance(error, discord.HTTPException) and getattr(error, "code", None) == 40060:
        logger.info("%s interaction was already acknowledged", context)
        return

    reference = uuid4().hex[:8]
    logger.exception("%s failed [reference=%s]", context, reference, exc_info=error)
    message = _text(
        interaction,
        f"❌ Something went wrong. Try again later. Reference: `{reference}`",
        f"❌ เกิดข้อผิดพลาด กรุณาลองใหม่ภายหลัง รหัสอ้างอิง: `{reference}`",
    )
    try:
        await safe_send(interaction, content=message, ephemeral=True)
    except (discord.NotFound, discord.HTTPException):
        logger.warning("Could not deliver error response [reference=%s]", reference)


def _normalize_virtual_key(raw_value: str) -> str:
    virtual_key = raw_value.strip()
    if len(virtual_key) < 8 or not virtual_key.startswith("sk-"):
        raise ValueError("Virtual key must start with 'sk-' and contain at least 8 characters.")
    if any(character.isspace() for character in virtual_key):
        raise ValueError("Virtual key cannot contain whitespace.")
    return virtual_key


async def _send_usage_followup(
    interaction: discord.Interaction,
    virtual_key: str,
    data: dict | None = None,
):
    try:
        usage_data = data if data is not None else await api.fetch_usage(virtual_key)
        embed = await embeds.format_usage_embed(usage_data, thai=_is_thai(interaction))
        embed.set_footer(
            text=f"{'เรียกโดย' if _is_thai(interaction) else 'Requested by'} {interaction.user}"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as error:
        await interaction.followup.send(
            embeds._error_message(
                error.status,
                "usage data",
                thai=_is_thai(interaction),
                user_credential=error.status == 404,
            ),
            ephemeral=True,
        )
    except Exception as error:  # Boundary: always acknowledge Discord interactions.
        await _handle_interaction_error(interaction, error, "usage-followup")


class ModelPaginatorView(discord.ui.View):
    """Bounded previous/next navigation for model result pages."""

    def __init__(self, pages: list[discord.Embed], user_id: int, thai: bool = False):
        super().__init__(timeout=120)
        self.pages = pages
        self.user_id = user_id
        self.index = 0
        self.message = None
        if thai:
            self.previous.label = "ก่อนหน้า"
            self.next.label = "ถัดไป"
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This result belongs to another user.", ephemeral=True
        )
        return False

    @discord.ui.button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.info("Model paginator message expired before controls could be disabled")


async def _send_models_followup(interaction: discord.Interaction, virtual_key: str):
    try:
        models_response = await api.fetch_models(virtual_key)
        pricing_lookup = await api.fetch_model_info_all()
        thai = _is_thai(interaction)
        pages = embeds.format_models_info_embeds(models_response, pricing_lookup, thai=thai)
        for page in pages:
            page.set_footer(text=f"{'เรียกโดย' if thai else 'Requested by'} {interaction.user}")
        if len(pages) == 1:
            await interaction.followup.send(embed=pages[0], ephemeral=True)
            return
        view = ModelPaginatorView(pages, interaction.user.id, thai)
        view.message = await interaction.followup.send(
            embed=pages[0],
            view=view,
            ephemeral=True,
            wait=True,
        )
    except aiohttp.ClientResponseError as error:
        await interaction.followup.send(
            embeds._error_message(error.status, "model data", thai=_is_thai(interaction)),
            ephemeral=True,
        )
    except Exception as error:  # Boundary: always acknowledge Discord interactions.
        await _handle_interaction_error(interaction, error, "models-followup")


async def _send_usage_daily_followup(
    interaction: discord.Interaction,
    virtual_key: str,
    key_data: dict | None = None,
):
    try:
        usage_data = key_data if key_data is not None else await api.fetch_usage(virtual_key)
        team_info = embeds._resolve_team_info(usage_data)
        if team_info is None or not team_info["team_id"]:
            await interaction.followup.send(
                _text(
                    interaction,
                    "❌ No LiteLLM team is associated with this key. Contact your administrator.",
                    "❌ คีย์นี้ยังไม่มี LiteLLM team กรุณาติดต่อผู้ดูแลระบบ",
                ),
                ephemeral=True,
            )
            return
        activity = await api.fetch_team_daily_activity(team_info["team_id"])
        embed = await embeds.format_token_usage_embed(
            team_info,
            activity,
            thai=_is_thai(interaction),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except aiohttp.ClientResponseError as error:
        user_credential = error.status == 404
        await interaction.followup.send(
            embeds._error_message(
                error.status,
                "team usage data",
                thai=_is_thai(interaction),
                user_credential=user_credential,
            ),
            ephemeral=True,
        )
    except Exception as error:  # Boundary: always acknowledge Discord interactions.
        await _handle_interaction_error(interaction, error, "usage-daily-followup")


class SetupButton(discord.ui.Button):
    def __init__(self, action: str, thai: bool):
        super().__init__(
            label="กรอก Virtual Key" if thai else "Enter Virtual Key",
            emoji="🔑",
            style=discord.ButtonStyle.primary,
        )
        self.action = action
        self.thai = thai

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(KeySetupModal(self.action, self.thai))


class KeySetupView(discord.ui.View):
    def __init__(self, action: str, thai: bool):
        super().__init__(timeout=120)
        self.message = None
        self.add_item(SetupButton(action, thai))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.info("Setup consent message expired before controls could be disabled")


async def _show_key_setup(interaction: discord.Interaction, action: str):
    thai = _is_thai(interaction)
    view = KeySetupView(action, thai)
    message = _text(
        interaction,
        "🔐 **Before you continue**\nYour LiteLLM virtual key is used only to fetch "
        "your usage and models. It is encrypted at rest. You can replace it with "
        "`/reset-key` or permanently remove it with `/delete-key`.",
        "🔐 **ก่อนดำเนินการต่อ**\nVirtual key ใช้สำหรับดึง usage และ models ของคุณเท่านั้น "
        "ระบบเข้ารหัสคีย์ขณะจัดเก็บ เปลี่ยนได้ด้วย `/reset-key` และลบถาวรด้วย `/delete-key`",
    )
    view.message = await safe_send(interaction, content=message, view=view, ephemeral=True)


async def _get_stored_key(interaction: discord.Interaction) -> str | None:
    try:
        return await db.get_user_key(str(interaction.user.id))
    except db.KeyDecryptionError:
        await safe_send(
            interaction,
            content=_text(
                interaction,
                "🔐 Your stored key can no longer be decrypted. Use `/reset-key` to replace it "
                "or `/delete-key` to remove it.",
                "🔐 ไม่สามารถถอดรหัสคีย์เดิมได้ ใช้ `/reset-key` เพื่อเปลี่ยนคีย์ หรือ `/delete-key` เพื่อลบข้อมูล",
            ),
            ephemeral=True,
        )
        return None


async def handle_usage(interaction: discord.Interaction):
    try:
        if not await _check_rate_limit(interaction):
            return
        virtual_key = await _get_stored_key(interaction)
        if virtual_key is None:
            if not interaction.response.is_done():
                await _show_key_setup(interaction, "usage")
            return
        await interaction.response.defer(ephemeral=True)
        await _send_usage_followup(interaction, virtual_key)
    except Exception as error:  # Command boundary.
        await _handle_interaction_error(interaction, error, "usage")


async def handle_models(interaction: discord.Interaction):
    try:
        if not await _check_rate_limit(interaction):
            return
        virtual_key = await _get_stored_key(interaction)
        if virtual_key is None:
            if not interaction.response.is_done():
                await _show_key_setup(interaction, "models")
            return
        await interaction.response.defer(ephemeral=True)
        await _send_models_followup(interaction, virtual_key)
    except Exception as error:  # Command boundary.
        await _handle_interaction_error(interaction, error, "models")


async def handle_usage_daily(interaction: discord.Interaction):
    try:
        if not await _check_rate_limit(interaction):
            return
        virtual_key = await _get_stored_key(interaction)
        if virtual_key is None:
            if not interaction.response.is_done():
                await _show_key_setup(interaction, "usage-daily")
            return
        await interaction.response.defer(ephemeral=True)
        await _send_usage_daily_followup(interaction, virtual_key)
    except Exception as error:  # Command boundary.
        await _handle_interaction_error(interaction, error, "usage-daily")


async def handle_reset_key(interaction: discord.Interaction):
    try:
        if not await _check_rate_limit(interaction):
            return
        if not await db.has_user_key(str(interaction.user.id)):
            await safe_send(
                interaction,
                content=_text(
                    interaction,
                    "⚠️ No key is registered yet. Use `/usage` to start setup.",
                    "⚠️ ยังไม่มีคีย์ที่ลงทะเบียน ใช้ `/usage` เพื่อเริ่มตั้งค่า",
                ),
                ephemeral=True,
            )
            return
        await safe_send_modal(interaction, ResetKeyModal(_is_thai(interaction)))
    except Exception as error:  # Command boundary.
        await _handle_interaction_error(interaction, error, "reset-key")


async def handle_delete_key(interaction: discord.Interaction):
    try:
        if not await _check_rate_limit(interaction):
            return
        if not await db.has_user_key(str(interaction.user.id)):
            await safe_send(
                interaction,
                content=_text(
                    interaction,
                    "⚠️ You do not have any stored data to delete.",
                    "⚠️ คุณไม่มีข้อมูลที่จัดเก็บไว้ให้ลบ",
                ),
                ephemeral=True,
            )
            return
        view = DeleteConfirmView(str(interaction.user.id), _is_thai(interaction))
        view.message = await safe_send(
            interaction,
            content=_text(
                interaction,
                "⚠️ **Are you sure?** This permanently deletes your virtual key and stored data.",
                "⚠️ **ยืนยันการลบหรือไม่?** การดำเนินการนี้จะลบ virtual key และข้อมูลถาวร",
            ),
            view=view,
            ephemeral=True,
        )
    except Exception as error:  # Command boundary.
        await _handle_interaction_error(interaction, error, "delete-key")


class ActionButton(discord.ui.Button):
    def __init__(self, action: str, label: str, emoji: str, style: discord.ButtonStyle, row: int):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        handlers = {
            "usage": handle_usage,
            "usage-daily": handle_usage_daily,
            "models": handle_models,
            "reset-key": handle_reset_key,
            "delete-key": handle_delete_key,
        }
        await handlers[self.action](interaction)


class HelpView(discord.ui.View):
    def __init__(self, thai: bool = False):
        super().__init__(timeout=120)
        self.message = None
        labels = {
            "usage": "สถิติการใช้งาน" if thai else "Usage Stats",
            "usage-daily": "การใช้งานวันนี้" if thai else "Daily Usage",
            "models": "โมเดล" if thai else "Models",
            "reset-key": "เปลี่ยนคีย์" if thai else "Reset Key",
            "delete-key": "ลบคีย์" if thai else "Delete Key",
        }
        self.add_item(ActionButton("usage", labels["usage"], "📊", discord.ButtonStyle.primary, 0))
        self.add_item(
            ActionButton("usage-daily", labels["usage-daily"], "🪙", discord.ButtonStyle.primary, 0)
        )
        self.add_item(
            ActionButton("models", labels["models"], "🤖", discord.ButtonStyle.primary, 0)
        )
        self.add_item(
            ActionButton("reset-key", labels["reset-key"], "🔑", discord.ButtonStyle.secondary, 1)
        )
        self.add_item(
            ActionButton("delete-key", labels["delete-key"], "🗑️", discord.ButtonStyle.danger, 1)
        )

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.info("Help message expired before controls could be disabled")


class DeleteConfirmButton(discord.ui.Button):
    def __init__(self, user_id: str, thai: bool):
        super().__init__(
            label="ยืนยันการลบ" if thai else "Yes, Delete",
            style=discord.ButtonStyle.danger,
        )
        self.user_id = user_id
        self.thai = thai

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "This action belongs to another user.", ephemeral=True
            )
            return
        try:
            deleted = await db.delete_user_key(self.user_id)
            message = (
                ("✅ ลบข้อมูลเรียบร้อยแล้ว" if self.thai else "✅ Your data has been deleted.")
                if deleted
                else ("❌ ไม่พบข้อมูลที่ต้องการลบ" if self.thai else "❌ No stored data was found.")
            )
            await interaction.response.edit_message(content=message, view=None)
            self.view.stop()
        except Exception as error:  # Interaction boundary.
            await _handle_interaction_error(interaction, error, "delete-confirm")


class DeleteCancelButton(discord.ui.Button):
    def __init__(self, thai: bool):
        super().__init__(
            label="ยกเลิก" if thai else "Cancel",
            style=discord.ButtonStyle.secondary,
        )
        self.thai = thai

    async def callback(self, interaction: discord.Interaction):
        message = "✅ ยกเลิกแล้ว ข้อมูลยังปลอดภัย" if self.thai else "✅ Cancelled. Your data is safe."
        await interaction.response.edit_message(content=message, view=None)
        self.view.stop()


class DeleteConfirmView(discord.ui.View):
    def __init__(self, user_id: str, thai: bool):
        super().__init__(timeout=60)
        self.message = None
        self.add_item(DeleteConfirmButton(user_id, thai))
        self.add_item(DeleteCancelButton(thai))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                logger.info("Delete confirmation expired before controls could be disabled")


class KeySetupModal(discord.ui.Modal):
    def __init__(self, action: str = "usage", thai: bool = False):
        super().__init__(title="🔑 ตั้งค่า Virtual Key" if thai else "🔑 Set Up Virtual Key")
        self.action = action
        self.thai = thai
        self.key_input = discord.ui.TextInput(
            label="LiteLLM Virtual Key",
            placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
            required=True,
            min_length=8,
            max_length=500,
        )
        self.add_item(self.key_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            virtual_key = _normalize_virtual_key(self.key_input.value)
            verified_data = await api.fetch_usage(virtual_key)
            await db.save_user_key(str(interaction.user.id), virtual_key)
            await interaction.followup.send(
                "✅ บันทึกคีย์แล้ว" if self.thai else "✅ Virtual key verified and saved.",
                ephemeral=True,
            )
            if self.action == "usage":
                await _send_usage_followup(interaction, virtual_key, verified_data)
            elif self.action == "usage-daily":
                await _send_usage_daily_followup(interaction, virtual_key, verified_data)
            else:
                await _send_models_followup(interaction, virtual_key)
        except ValueError as error:
            message = (
                "❌ Virtual key ต้องขึ้นต้นด้วย `sk-` มีอย่างน้อย 8 ตัวอักษร และไม่มีช่องว่าง"
                if self.thai
                else f"❌ {error}"
            )
            await interaction.followup.send(message, ephemeral=True)
        except aiohttp.ClientResponseError as error:
            await interaction.followup.send(
                embeds._error_message(
                    error.status,
                    "key",
                    thai=self.thai,
                    user_credential=error.status == 404,
                ),
                ephemeral=True,
            )
        except Exception as error:  # Modal boundary.
            await _handle_interaction_error(interaction, error, "key-setup")


class ResetKeyModal(discord.ui.Modal):
    def __init__(self, thai: bool = False):
        super().__init__(title="🔑 เปลี่ยน Virtual Key" if thai else "🔑 Reset Virtual Key")
        self.thai = thai
        self.key_input = discord.ui.TextInput(
            label="LiteLLM Virtual Key ใหม่" if thai else "New LiteLLM Virtual Key",
            placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
            required=True,
            min_length=8,
            max_length=500,
        )
        self.add_item(self.key_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            virtual_key = _normalize_virtual_key(self.key_input.value)
            await api.fetch_usage(virtual_key)
            await db.save_user_key(str(interaction.user.id), virtual_key)
            await interaction.followup.send(
                "✅ เปลี่ยนคีย์เรียบร้อยแล้ว" if self.thai else "✅ Virtual key verified and updated.",
                ephemeral=True,
            )
        except ValueError as error:
            message = (
                "❌ Virtual key ต้องขึ้นต้นด้วย `sk-` มีอย่างน้อย 8 ตัวอักษร และไม่มีช่องว่าง"
                if self.thai
                else f"❌ {error}"
            )
            await interaction.followup.send(message, ephemeral=True)
        except aiohttp.ClientResponseError as error:
            await interaction.followup.send(
                embeds._error_message(
                    error.status,
                    "key",
                    thai=self.thai,
                    user_credential=error.status == 404,
                ),
                ephemeral=True,
            )
        except Exception as error:  # Modal boundary.
            await _handle_interaction_error(interaction, error, "reset-key-modal")


class ThaiTranslator(app_commands.Translator):
    translations: ClassVar[dict[str, str]] = {
        "Check your LiteLLM usage statistics": "ดูสถิติการใช้งาน LiteLLM",
        "List all models you have access to": "ดูโมเดลทั้งหมดที่คุณมีสิทธิ์ใช้",
        "Reset your LiteLLM virtual key": "เปลี่ยน LiteLLM virtual key",
        "Delete your data from the system": "ลบคีย์และข้อมูลของคุณจากระบบ",
        "Check today's usage dashboard (spend, tokens, requests)": "ดู spend, tokens และ requests ของวันนี้",
        "Show all available commands with interactive buttons": "ดูคำสั่งทั้งหมดพร้อมปุ่มใช้งาน",
    }

    async def translate(self, string, locale, _context):
        if locale is discord.Locale.thai:
            return self.translations.get(string.message)
        return None


class LiteLLMBot(discord_commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix=discord_commands.when_mentioned, intents=intents)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self):
        await db.init_db()
        await self.tree.set_translator(ThaiTranslator())
        await self.tree.sync()
        logger.info("Database initialized and application commands synced")

    async def on_ready(self):
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        await _handle_interaction_error(interaction, error, "application-command")

    async def close(self):
        await api.close_session()
        await db.close_db()
        await super().close()


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

    @bot.tree.command(
        name="usage-daily",
        description="Check today's usage dashboard (spend, tokens, requests)",
    )
    async def usage_daily(interaction: discord.Interaction):
        await handle_usage_daily(interaction)

    @bot.tree.command(
        name="help",
        description="Show all available commands with interactive buttons",
    )
    async def help_command(interaction: discord.Interaction):
        try:
            thai = _is_thai(interaction)
            view = HelpView(thai)
            view.message = await safe_send(
                interaction,
                embed=embeds.build_help_embed(interaction.user, thai=thai),
                view=view,
                ephemeral=True,
            )
        except Exception as error:  # Command boundary.
            await _handle_interaction_error(interaction, error, "help")
