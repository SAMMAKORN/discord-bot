"""LiteLLM proxy API client with shared aiohttp session."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

# ── Shared HTTP Session ─────────────────────────────────────────
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)
_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()


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
    LITELLM_BASE_URL = base_url
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


async def fetch_model_info_all() -> dict:
    """GET /model/info — returns ALL model configs keyed by model_name.

    Uses master key. Returns empty dict on failure.
    """
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/model/info"
    try:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                lookup = {}
                for entry in (data.get("data") or []):
                    name = entry.get("model_name", "")
                    info = entry.get("model_info", {})
                    if name and isinstance(info, dict):
                        lookup[name] = info
                return lookup
    except (aiohttp.ClientResponseError, Exception) as e:
        print(f"[api] fetch_model_info_all failed: {type(e).__name__}: {e}")
    return {}


async def fetch_usd_thb_rate() -> float:
    """Fetch live USD/THB exchange rate from exchangerate API."""
    session = await get_session()
    url = "https://open.er-api.com/v6/latest/USD"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        resp.raise_for_status()
        data = await resp.json()
        rate = data.get("rates", {}).get("THB", 0.0)
        return float(rate) if rate else 0.0


async def fetch_team_list() -> list[dict]:
    """GET /team/list — returns all teams managed by the proxy."""
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/team/list"
    async with session.get(
        url,
        headers={"Authorization": f"Bearer {MASTER_KEY}"},
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data if isinstance(data, list) else data.get("data", [])


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
