import unittest
from types import SimpleNamespace
from unittest.mock import patch

import discord

from bot import commands
from bot.commands import LiteLLMBot, ThaiTranslator, _normalize_virtual_key


class CommandTests(unittest.TestCase):
    def test_virtual_key_is_trimmed_and_validated(self):
        self.assertEqual(_normalize_virtual_key("  sk-12345  "), "sk-12345")
        for invalid in ("", "short", "sk-a bcd", "not-a-key"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                _normalize_virtual_key(invalid)

    def test_bot_does_not_request_message_content_intent(self):
        bot = LiteLLMBot()
        self.assertFalse(bot.intents.message_content)
        self.assertEqual(bot.intents.value & discord.Intents.message_content.flag, 0)


class TranslatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_thai_command_description_translation(self):
        translator = ThaiTranslator()
        source = discord.app_commands.locale_str("Check your LiteLLM usage statistics")
        translated = await translator.translate(source, discord.Locale.thai, None)
        self.assertEqual(translated, "ดูสถิติการใช้งาน LiteLLM")


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_removes_stale_users(self):
        interaction = SimpleNamespace(user=SimpleNamespace(id=42))
        commands._last_action.clear()
        commands._last_action[1] = 1.0
        commands._last_rate_limit_cleanup = 0.0

        with patch("bot.commands.time.monotonic", return_value=1_000.0):
            allowed = await commands._check_rate_limit(interaction)

        self.assertTrue(allowed)
        self.assertNotIn(1, commands._last_action)
        self.assertIn(42, commands._last_action)
