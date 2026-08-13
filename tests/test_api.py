import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot import api


class ApiTests(unittest.TestCase):
    def test_configure_removes_trailing_slash(self):
        api.configure("https://litellm.example///", "master")
        self.assertEqual(api.LITELLM_BASE_URL, "https://litellm.example")
        self.assertEqual(api.MASTER_KEY, "master")


class AsyncApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        api._model_info_cache = None

    async def test_malformed_model_metadata_degrades_to_empty_lookup(self):
        response = MagicMock()
        response.__aenter__.return_value = response
        response.raise_for_status.return_value = None
        response.json = AsyncMock(return_value=[])
        session = MagicMock()
        session.get.return_value = response
        api._model_info_cache = None

        with patch("bot.api.get_session", new=AsyncMock(return_value=session)):
            result = await api.fetch_model_info_all(force_refresh=True)

        self.assertEqual(result, {})
