import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from bot import api


def _json_session(payload, *, raises=None):
    """Build a mock aiohttp session whose GET yields *payload*."""
    response = MagicMock()
    response.__aenter__.return_value = response
    if raises is not None:
        response.raise_for_status.side_effect = raises
    else:
        response.raise_for_status.return_value = None
    response.json = AsyncMock(return_value=payload)
    session = MagicMock()
    session.get.return_value = response
    return session


class ApiTests(unittest.TestCase):
    def test_configure_removes_trailing_slash(self):
        api.configure("https://litellm.example///", "master")
        self.assertEqual(api.LITELLM_BASE_URL, "https://litellm.example")
        self.assertEqual(api.MASTER_KEY, "master")


class AsyncApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        api._model_info_cache = None
        api._exchange_rate_cache = None

    async def test_malformed_model_metadata_degrades_to_empty_lookup(self):
        session = _json_session([])
        api._model_info_cache = None

        with patch("bot.api.get_session", new=AsyncMock(return_value=session)):
            result = await api.fetch_model_info_all(force_refresh=True)

        self.assertEqual(result, {})

    async def test_exchange_rate_failure_is_cached_and_not_retried(self):
        error = aiohttp.ClientError("upstream down")
        session = _json_session(None, raises=error)
        api._exchange_rate_cache = None

        with patch("bot.api.get_session", new=AsyncMock(return_value=session)):
            first = await api.fetch_usd_thb_rate()
            second = await api.fetch_usd_thb_rate()

        self.assertEqual(first, 0.0)
        self.assertEqual(second, 0.0)
        # The failure is cached, so the second call must not hit the network again.
        self.assertEqual(session.get.call_count, 1)

    async def test_team_alias_read_from_nested_and_flat_payloads(self):
        # LiteLLM /team/info nests the record under "team_info"; tolerate both shapes.
        for payload in ({"team_info": {"team_alias": "ai-officer"}}, {"team_alias": "ai-officer"}):
            with self.subTest(payload=payload):
                session = _json_session(payload)
                with patch("bot.api.get_session", new=AsyncMock(return_value=session)):
                    self.assertEqual(await api.fetch_team_alias("t1"), "ai-officer")

    async def test_team_alias_returns_none_when_lookup_fails(self):
        session = _json_session(None, raises=aiohttp.ClientError("boom"))
        with patch("bot.api.get_session", new=AsyncMock(return_value=session)):
            self.assertIsNone(await api.fetch_team_alias("t1"))
