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
_model_info_lock = asyncio.Lock()
_exchange_rate_lock = asyncio.Lock()
_model_info_cache: tuple[float, dict] | None = None
# (expires_at_monotonic, rate) — failures are cached briefly so an outage in the
# FX provider cannot serialize every /usage invocation behind a fresh request.
_exchange_rate_cache: tuple[float, float] | None = None
_MODEL_INFO_TTL = 600
_EXCHANGE_RATE_TTL = 3600
_EXCHANGE_RATE_FAILURE_TTL = 60
# One day of team activity fits in a single large page; the cap only guards
# against a proxy that keeps reporting has_more.
_DAILY_ACTIVITY_PAGE_SIZE = 1000
_DAILY_ACTIVITY_MAX_PAGES = 20


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

    async with _model_info_lock:
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

        if not isinstance(data, dict):
            logger.warning("Model metadata response was not a JSON object")
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
    """Return the USD/THB rate, or ``0.0`` when it cannot be determined."""
    global _exchange_rate_cache
    if _exchange_rate_cache and time.monotonic() < _exchange_rate_cache[0]:
        return _exchange_rate_cache[1]

    async with _exchange_rate_lock:
        if _exchange_rate_cache and time.monotonic() < _exchange_rate_cache[0]:
            return _exchange_rate_cache[1]

        session = await get_session()
        url = "https://open.er-api.com/v6/latest/USD"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                resp.raise_for_status()
                data = await resp.json()
            rates = data.get("rates") if isinstance(data, dict) else None
            rate = float(rates.get("THB", 0.0)) if isinstance(rates, dict) else 0.0
        except (TimeoutError, aiohttp.ClientError, TypeError, ValueError) as exc:
            logger.warning("Could not refresh USD/THB rate: %s", exc)
            rate = 0.0

        ttl = _EXCHANGE_RATE_TTL if rate > 0 else _EXCHANGE_RATE_FAILURE_TTL
        _exchange_rate_cache = (time.monotonic() + ttl, rate)
        return rate


async def fetch_team_alias(team_id: str) -> str | None:
    """GET /team/info — returns the team's display alias, or ``None``.

    ``/key/info`` only carries ``team_id``, so the alias needs a second lookup.
    Failures are swallowed: a missing alias must not fail the whole dashboard.
    """
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/team/info"
    try:
        async with session.get(
            url,
            params={"team_id": team_id},
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except (TimeoutError, aiohttp.ClientError) as exc:
        logger.warning("Could not resolve team alias for %s: %s", team_id, exc)
        return None

    if not isinstance(data, dict):
        return None
    nested = data.get("team_info")
    info = nested if isinstance(nested, dict) else data
    alias = info.get("team_alias")
    return str(alias) if alias else None


def _merge_activity_metadata(totals: dict, page_metadata: dict) -> dict:
    """Accumulate the per-page ``total_*`` counters into one metadata block."""
    for name, value in page_metadata.items():
        if not name.startswith("total_") or name == "total_pages":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        totals[name] = totals.get(name, 0) + value
    return totals


async def fetch_team_daily_activity(team_id: str) -> dict:
    """GET /team/daily/activity — today only, following every page.

    LiteLLM paginates the per-key breakdown, and a single key's rows can straddle
    the page boundary: page 1 carries its request counts while the tokens and
    spend sit on page 2. Reading page 1 alone is what made the dashboard report
    real request counts next to zero tokens, so walk the pages and merge them.
    """
    today = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d")
    session = await get_session()
    url = f"{LITELLM_BASE_URL}/team/daily/activity"
    results: list = []
    metadata: dict = {}
    page = 1

    while page <= _DAILY_ACTIVITY_MAX_PAGES:
        async with session.get(
            url,
            params={
                "team_id": team_id,
                "start_date": today,
                "end_date": today,
                "page": page,
                "page_size": _DAILY_ACTIVITY_PAGE_SIZE,
            },
            headers={"Authorization": f"Bearer {MASTER_KEY}"},
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()

        if not isinstance(payload, dict):
            logger.warning("Daily activity page %s was not a JSON object", page)
            break

        page_results = payload.get("results")
        if isinstance(page_results, list):
            results.extend(page_results)

        page_metadata = payload.get("metadata")
        page_metadata = page_metadata if isinstance(page_metadata, dict) else {}
        _merge_activity_metadata(metadata, page_metadata)

        total_pages = page_metadata.get("total_pages")
        if not page_metadata.get("has_more"):
            break
        if isinstance(total_pages, int) and page >= total_pages:
            break
        page += 1
    else:
        logger.warning(
            "Stopped paging /team/daily/activity for %s at the %s-page cap",
            team_id,
            _DAILY_ACTIVITY_MAX_PAGES,
        )

    metadata["pages_fetched"] = page
    return {"results": results, "metadata": metadata}
