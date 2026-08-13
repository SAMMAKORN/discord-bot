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

    async def test_rate_limits_use_the_field_names_litellm_returns(self):
        # /key/info reports rpm_limit / tpm_limit, not rpm_requests.
        info = {"rpm_limit": 60, "tpm_limit": 90000, "max_parallel_requests": 5}
        with patch("bot.embeds.fetch_usd_thb_rate", new=AsyncMock(return_value=0)):
            result = await embeds.format_usage_embed({"info": info})
        limits = next(field.value for field in result.fields if "Rate Limits" in field.name)
        self.assertEqual(limits, "60 req/min, 90,000 tok/min, 5 parallel")

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

    async def test_daily_metrics_match_alias_containing_markdown(self):
        alias = "sammakorn_dev_key"
        activity = {
            "results": [
                {
                    "breakdown": {
                        "api_keys": {
                            "hash": {
                                "metadata": {"key_alias": alias},
                                "metrics": {"spend": 12.5, "total_tokens": 1000, "api_requests": 7},
                            }
                        }
                    }
                }
            ]
        }
        team_info = {"team_alias": "sam", "team_id": "t1", "key_alias": alias}
        with patch("bot.embeds.fetch_usd_thb_rate", new=AsyncMock(return_value=0)):
            result = await embeds.format_token_usage_embed(team_info, activity)

        values = {field.name: field.value for field in result.fields}
        self.assertNotIn("⚠️ Note", values)
        self.assertIn("`7`", values["📊 **Total Requests**"])
        self.assertIn("$12.50", values["💰 **Total Spend**"])
