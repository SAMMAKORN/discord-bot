import unittest
from unittest.mock import AsyncMock, patch

from bot import embeds


class EmbedTests(unittest.IsolatedAsyncioTestCase):
    async def test_usage_normalizes_null_and_string_numbers(self):
        with patch("bot.embeds.fetch_usd_thb_rate", new=AsyncMock(return_value=35.0)):
            null_embed = await embeds.format_usage_embed({"info": {"spend": None}})
            string_embed = await embeds.format_usage_embed({"info": {"spend": "1.25"}})
        self.assertLessEqual(len(null_embed), 6000)
        self.assertIn("$1.25 USD", string_embed.fields[1].value)

    async def test_thai_usage_localizes_primary_fields(self):
        with patch("bot.embeds.fetch_usd_thb_rate", new=AsyncMock(return_value=0)):
            result = await embeds.format_usage_embed({"info": {}}, thai=True)
        self.assertEqual(result.title, "📊 รายงานการใช้งาน LiteLLM")
        self.assertTrue(any(field.name == "💰 ค่าใช้จ่ายรวม" for field in result.fields))

    def test_model_pages_never_exceed_discord_limits(self):
        models = {
            "data": [
                {"id": f"provider{provider}/model-{model}-with-a-realistically-long-name"}
                for provider in range(30)
                for model in range(15)
            ]
        }
        pages = embeds.format_models_info_embeds(models, {})
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertLessEqual(len(page.fields), 25)
            self.assertLessEqual(len(page), 6000)
            self.assertTrue(all(len(field.value) <= 1024 for field in page.fields))

    def test_model_lookup_uses_longest_prefix(self):
        pricing = {"gpt-4": {"marker": "wrong"}, "gpt-4o-mini": {"marker": "right"}}
        result = embeds._lookup_model_info(pricing, "gpt-4o-mini-2025")
        self.assertEqual(result["marker"], "right")

    def test_daily_metrics_do_not_use_ambiguous_suffix(self):
        results = [
            {
                "breakdown": {
                    "api_keys": {
                        "a": {
                            "metadata": {"key_alias": "alpha-12345678"},
                            "metrics": {"spend": 100, "api_requests": 20},
                        }
                    }
                }
            }
        ]
        totals, found = embeds._extract_key_metrics(results, "owner-12345678")
        self.assertFalse(found)
        self.assertEqual(totals["spend"], 0)
