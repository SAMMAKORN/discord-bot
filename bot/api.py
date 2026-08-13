"""LiteLLM proxy API client with shared aiohttp session."""

import asyncio
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

logger = logging.getLogger(__name__)

# ── Shared HTTP Session ─────────────────────────────────────────
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()
_cache_lock = asyncio.Lock()
_model_info_cache: tuple[float, dict] | None = None
_exchange_rate_cache: tuple[float, float] | None = None
_MODEL_INFO_TTL = 600
_EXCHANGE_RATE_TTL = 3600


async def get_session() -> aiohttp.ClientSession:
    """Return a shared aiohttp.ClientSession for all API calls."""
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _session_lock:
        if _session is not None and not _session.closed:
            return _session
        _session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
        return _session


async def close_session():
    """Close the shared HTTP session."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None


# ── Configuration ───────────────────────────────────────────────
# These are set by main.py after loading env vars.
LITELLM_BASE_URL: str = ""
MASTER_KEY: str = ""


def configure(base_url: str, master_key: str):
    """Set API base URL and master key (called at bot startup)."""
    global LITELLM_BASE_URL, MASTER_KEY
    LITELLM_BASE_URL = base_url.rstrip("/")
    MASTER_KEY = master_key


# ── LiteLLM API Endpoints ──────────────────────────────────────
async def fetch_usage(virtual_key: str) -> dict:
    """GET /key/info — returns key metadata and spend."""
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/key/info"
    async with session.get(
        url,
        params={"key": virtual_key},
        headers={"Authorization": f"Bearer {MASTER_KEY}"},
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_models(virtual_key: str) -> dict:
    """GET /v1/models — returns accessible model list."""
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/v1/models"
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {virtual_key}"},
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_model_info_all(*, force_refresh: bool = False) -> dict:
    """GET /model/info — returns ALL model configs keyed by model_name.

    Uses master key. Returns empty dict on failure.
    """
    global _model_info_cache
    now = time.monotonic()
    if not force_refresh and _model_info_cache and now - _model_info_cache[0] < _MODEL_INFO_TTL:
        return _model_info_cache[1]

    async with _cache_lock:
        now = time.monotonic()
        if not force_refresh and _model_info_cache and now - _model_info_cache[0] < _MODEL_INFO_TTL:
            return _model_info_cache[1]

        session = await get_session()
        url = f"{LITELLM_BASE_URL}/model/info"
        try:
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {MASTER_KEY}"},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (TimeoutError, aiohttp.ClientError) as exc:
            logger.warning("Could not refresh model metadata: %s", exc)
            return _model_info_cache[1] if _model_info_cache else {}

        lookup = {}
        for entry in data.get("data") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("model_name", "")
            info = entry.get("model_info", {})
            if name and isinstance(info, dict):
                lookup[name] = info
        _model_info_cache = (time.monotonic(), lookup)
        return lookup


async def fetch_usd_thb_rate() -> float:
    """Fetch live USD/THB exchange rate from exchangerate API."""
    global _exchange_rate_cache
    now = time.monotonic()
    if _exchange_rate_cache and now - _exchange_rate_cache[0] < _EXCHANGE_RATE_TTL:
        return _exchange_rate_cache[1]

    async with _cache_lock:
        now = time.monotonic()
        if _exchange_rate_cache and now - _exchange_rate_cache[0] < _EXCHANGE_RATE_TTL:
            return _exchange_rate_cache[1]

        session = await get_session()
        url = "https://open.er-api.com/v6/latest/USD"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        try:
            rate = float((data.get("rates") or {}).get("THB", 0.0))
        except (TypeError, ValueError):
            rate = 0.0
        if rate > 0:
            _exchange_rate_cache = (time.monotonic(), rate)
        return rate


async def fetch_team_daily_activity(team_id: str) -> dict:
    """GET /team/daily/activity — today only."""
    today = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d")
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/team/daily/activity"
    async with session.get(
        url,
        params={"team_id": team_id, "start_date": today, "end_date": today, "page": 1},
        headers={"Authorization": f"Bearer {MASTER_KEY}"},
    ) as resp:
        resp.raise_for_status()
        return await resp.json()
