"""Discord embed formatters for all bot responses."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import errors as discord_errors

from .api import fetch_usd_thb_rate


def _truncate_key(key: str) -> str:
    """Mask the leading characters of *key*, keeping only the last 8."""
    return f"****{key[-8:]}" if len(key) > 8 else key


# ── Provider Detection ─────────────────────────────────────────
_PROVIDER_HINTS = {
    "anthropic": ["claude-"],
    "openai": ["gpt-", "o1", "o3", "o4"],
    "google": ["gemini-"],
    "mistral": ["mistral"],
    "amazon": ["nova-"],
    "meta": ["llama"],
    "nvidia": ["nemotron", "nvidia/"],
    "microsoft": ["phi-"],
    "databricks": ["dbrx", "databricks-"],
    "cohere": ["command-"],
}

_PROVIDER_EMOJI = {
    "anthropic": "\U0001f7e3",
    "openai": "\U0001f535",
    "google": "\U0001f534",
    "nvidia": "\U0001f7e2",
    "qwen": "\U0001f7e0",
    "mistral": "\U0001f7e1",
    "amazon": "\U0001f536",
    "meta": "🦙",
    "other": "🔵",
}


def _detect_provider(model_id: str) -> str:
    """Detect provider from model name using prefix hints."""
    if "/" in model_id:
        return model_id.split("/")[0]
    lower = model_id.lower()
    for prov, prefixes in _PROVIDER_HINTS.items():
        for p in prefixes:
            if lower.startswith(p):
                return prov
    return "other"


def _format_short_num(n: int) -> str:
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"{val:g}M"
    if n >= 1_000:
        val = n / 1_000
        return f"{val:g}K"
    return str(n)


def _lookup_model_info(pricing_data: dict, model_id: str) -> dict:
    """Find model_info for model_id in pricing_data.

    pricing_data is keyed by model_name from /model/info.
    model_id from /v1/models might be a variant (e.g., "-thinking").
    Tries exact match, then suffix/substring fallback.
    """
    if model_id in pricing_data:
        return pricing_data[model_id]

    short = model_id.split("/")[-1] if "/" in model_id else model_id

    for pname, info in pricing_data.items():
        pshort = pname.split("/")[-1]
        if short == pshort:
            return info
        if short.startswith(pshort):
            return info
        if pshort.startswith(short):
            return info

    return {}


# ── Usage Embed ────────────────────────────────────────────────
async def format_usage_embed(data: dict) -> discord.Embed:
    """Build the /usage embed with live USD/THB rate."""
    data = data or {}
    info = data.get("info") or {}
    key = data.get("key", "N/A")

    spend = info.get("spend", 0.0)
    models = info.get("models", [])
    expires = info.get("expires", "N/A")
    config = info.get("config", {})
    max_budget = info.get("max_budget", None)
    key_name = info.get("key_name", "N/A")
    key_alias = info.get("key_alias", data.get("key_alias", None))
    last_active = info.get("last_active", None)

    # Rate limits
    rpm_limit = info.get("rpm_requests", None)
    tpm_limit = info.get("tpm_limit", None)
    max_parallel_requests = info.get("max_parallel_requests", None)

    try:
        usd_thb_rate = await fetch_usd_thb_rate()
    except Exception:
        usd_thb_rate = 0.0

    if usd_thb_rate and spend:
        thb = spend * usd_thb_rate
        spend_str = f"${spend:,.2f} USD\n฿{thb:,.2f} THB (1 USD = {usd_thb_rate:,.2f} THB)"
    else:
        spend_str = f"${spend:,.2f} USD"

    embed = discord.Embed(
        title="📊 LiteLLM Usage Report",
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=key_name)
    embed.add_field(name="🔑 Virtual Key", value=f"```{_truncate_key(key)}```", inline=True)

    if key_alias:
        embed.add_field(name="🏷️ Key Alias", value=key_alias, inline=True)

    embed.add_field(name="💰 Total Spend", value=spend_str, inline=False)
    embed.add_field(name="📅 Expires", value=str(expires), inline=True)

    if last_active:
        try:
            la_dt = datetime.fromisoformat(str(last_active).replace("Z", "+00:00"))
            la_bkk = la_dt.astimezone(ZoneInfo("Asia/Bangkok"))
            hour = la_bkk.strftime("%I").lstrip("0") or "12"
            la_str = f"{la_bkk:%b %d, %Y} at {hour}:{la_bkk:%M} {la_bkk:%p}"
        except Exception:
            la_str = str(last_active)
        embed.add_field(name="🕐 Last Active", value=la_str, inline=True)

    rate_parts = []
    if rpm_limit is not None:
        rate_parts.append(f"{rpm_limit:,} req/min")
    if tpm_limit is not None:
        rate_parts.append(f"{tpm_limit:,} tok/min")
    if max_parallel_requests is not None:
        rate_parts.append(f"{max_parallel_requests:,} parallel")
    if rate_parts:
        embed.add_field(name="⚡ Rate Limits", value=", ".join(rate_parts), inline=True)

    if max_budget is not None:
        embed.add_field(name="💵 Max Budget", value=f"${max_budget:,.2f}", inline=True)

    models_str = ", ".join(models) if models else "All models"
    models_display = models_str if len(models_str) <= 100 else f"{models_str[:97]}..."
    embed.add_field(name="🤖 Models", value=models_display, inline=True)

    if config:
        config_str = "\n".join(f"{k}: {v}" for k, v in config.items())
        embed.add_field(name="⚙️ Config", value=f"```{config_str}```", inline=False)

    return embed


# ── Models Embed ───────────────────────────────────────────────
def format_models_info_embed(models_resp: dict, pricing_data: dict) -> discord.Embed:
    """Build a models embed — provider, mode, tokens, cost/1M."""
    model_list = models_resp.get("data", []) if isinstance(models_resp, dict) else []

    if not model_list:
        return discord.Embed(
            title="🤖 Available Models",
            description="No model information available.",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )

    rows = []
    for m in model_list:
        if not isinstance(m, dict):
            continue
        model_id = m.get("id") or m.get("model") or "unknown"
        provider = _detect_provider(model_id)
        info = _lookup_model_info(pricing_data, model_id)

        rows.append({
            "provider": provider,
            "name": model_id,
            "mode": info.get("mode", "chat"),
            "max_input": info.get("max_input_tokens", 0) or 0,
            "max_output": info.get("max_output_tokens", 0) or 0,
            "price_input": info.get("input_cost_per_token"),
            "price_output": info.get("output_cost_per_token"),
        })

    if not rows:
        return discord.Embed(
            title="🤖 Available Models",
            description="No model information available.",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )

    groups = {}
    for row in rows:
        groups.setdefault(row["provider"], []).append(row)
    sorted_groups = dict(sorted(groups.items()))

    def _fmt_cost(r):
        pi = r["price_input"]
        po = r["price_output"]
        if pi is None and po is None:
            return "N/A"
        in_s = f"${(pi * 1_000_000):.2f}" if pi is not None else "—"
        out_s = f"${(po * 1_000_000):.2f}" if po is not None else "—"
        return f"{in_s}/{out_s}"

    total = sum(len(v) for v in sorted_groups.values())
    provider_count = len(sorted_groups)

    embed = discord.Embed(
        title="🤖 Available Models",
        description=f"**{total}** model(s) across **{provider_count}** provider(s)",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    for provider, prows in sorted_groups.items():
        emoji = _PROVIDER_EMOJI.get(provider, "🔵")
        field_name = f"{emoji} {provider}"
        # Discord field name limit is 60 chars; truncate if needed
        if len(field_name) > 60:
            field_name = field_name[:57] + "..."

        model_lines = []
        for r in prows:
            full_name = r["name"]
            tok_in = _format_short_num(r["max_input"]) if r["max_input"] else "—"
            tok_out = _format_short_num(r["max_output"]) if r["max_output"] else ""
            tok_str = f"{tok_in}" + (f" / {tok_out}" if tok_out else "")
            cost = _fmt_cost(r)
            model_lines.append(f"• `{full_name}`\n  **Tokens:** {tok_str}  **Cost:** {cost}")

        section = "\n".join(model_lines)

        # If the section exceeds 1000 chars, truncate at a model boundary
        # rather than hard-cutting mid-entry
        if len(section) > 1000:
            kept: list[str] = []
            skipped = 0
            running = ""
            separator = "\n"
            for ml in model_lines:
                candidate = running + separator + ml if running else ml
                summary = f"\n… and {len(model_lines)} more models"
                if len(candidate + summary) > 1000:
                    skipped += 1
                    continue
                kept.append(ml)
                running = candidate
            if skipped > 0:
                summary = f"\n… and {skipped} more models"
                section = separator.join(kept) + summary
            else:
                section = running

        # Final safety trim at a model boundary (never mid-entry)
        if len(section) > 1024:
            tail = section[:1021]
            # Find the last newline to avoid cutting mid-model
            last_newline = tail.rfind("\n")
            if last_newline > 500:
                tail = tail[:last_newline]
            section = tail + "..."

        try:
            embed.add_field(name=field_name, value=section, inline=False)
        except discord_errors.InvalidArgument:
            embed.add_field(name=provider, value=section[:1024], inline=False)

    return embed


# ── Team / Daily Usage Embed ───────────────────────────────────
def _extract_key_metrics(results: list[dict], key_alias: str) -> tuple[dict, bool]:
    """Sum metrics for a specific key_alias across results."""
    totals = {
        "spend": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "api_requests": 0,
    }
    found = False
    alias_suffix = key_alias[-8:] if len(key_alias) > 8 else key_alias
    for day in results:
        api_keys = day.get("breakdown", {}).get("api_keys", {})
        for _khash, kinfo in api_keys.items():
            remote_alias = (kinfo.get("metadata", {}).get("key_alias") or "")
            if remote_alias == key_alias or remote_alias.endswith(alias_suffix):
                m = kinfo.get("metrics", {})
                for k, v in m.items():
                    if k in totals and isinstance(v, (int, float)):
                        totals[k] += v
                found = True
                break
    return totals, found


def _find_team_for_key(team_list: list[dict], virtual_key: str) -> dict | None:
    key_alias = virtual_key[-8:] if len(virtual_key) > 8 else virtual_key
    for team in team_list:
        for key_info in (team.get("keys") or []):
            token = key_info.get("token", "")
            if token.endswith(key_alias):
                return {
                    "team_alias": team.get("team_alias", "Unknown"),
                    "team_id": team.get("team_id", ""),
                    "key_alias": key_info.get("key_alias", "Unknown"),
                }
    return None


def _resolve_team_info(team_list: list[dict], key_info: dict) -> dict | None:
    info = (key_info or {}).get("info", {}) or {}
    team_id = info.get("team_id")
    if team_id:
        for team in team_list:
            if team.get("team_id") == team_id:
                ka = info.get("key_alias") or info.get("key_name", "Unknown")
                return {
                    "team_alias": team.get("team_alias", "Unknown"),
                    "team_id": team_id,
                    "key_alias": ka,
                }
        return {
            "team_alias": "Unknown",
            "team_id": team_id,
            "key_alias": info.get("key_alias") or info.get("key_name", "Unknown"),
        }
    virtual_key = (key_info or {}).get("key", "")
    return _find_team_for_key(team_list, virtual_key)


async def format_token_usage_embed(team_info: dict, activity: dict) -> discord.Embed:
    """Format today's token usage stats for the user's key."""
    team_alias = team_info.get("team_alias", "Unknown")
    key_alias = team_info.get("key_alias", "Unknown")

    results = activity.get("results", [])
    key_metrics, key_found = _extract_key_metrics(results, key_alias)

    total_requests = key_metrics["api_requests"]
    total_successful = key_metrics["successful_requests"]
    total_failed = key_metrics["failed_requests"]
    total_tokens = key_metrics["total_tokens"]
    total_spend = key_metrics["spend"]

    avg_tokens = total_tokens // total_requests if total_requests > 0 else 0
    avg_spend = total_spend / total_requests if total_requests > 0 else 0.0

    try:
        usd_thb_rate = await fetch_usd_thb_rate()
    except Exception:
        usd_thb_rate = 0.0

    if usd_thb_rate and total_spend:
        thb = total_spend * usd_thb_rate
        spend_str = f"${total_spend:,.2f} USD\n฿{thb:,.2f} THB (1 USD = {usd_thb_rate:,.2f} THB)"
    else:
        spend_str = f"${total_spend:,.2f} USD"

    now_bkk = datetime.now(ZoneInfo("Asia/Bangkok"))
    today_str = now_bkk.strftime("%Y-%m-%d")

    color = discord.Color.blurple() if key_found else discord.Color.dark_gold()

    embed = discord.Embed(
        title=f"{key_alias} (team: {team_alias})",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="\U0001f4ca **Total Requests**",
        value=f"`{total_requests:,}`\n",
        inline=True,
    )
    embed.add_field(
        name="\U0001f999 **Total Tokens**",
        value=f"`{total_tokens:,}`\n",
        inline=True,
    )
    embed.add_field(
        name="\U0001f4b0 **Total Spend**",
        value=spend_str + "\n",
        inline=True,
    )

    embed.add_field(
        name="✅ **Successful**",
        value=f"`{total_successful:,}`",
        inline=True,
    )
    embed.add_field(
        name="❌ **Failed**",
        value=f"`{total_failed:,}`",
        inline=True,
    )
    embed.add_field(
        name="⚡ **Avg/request**",
        value=f"`{avg_tokens:,}` tok\n`${avg_spend:,.4f}`",
        inline=True,
    )

    if not key_found and not results:
        embed.add_field(
            name="⚠️ Note",
            value="No activity data found for today. The dashboard will show zeroes.",
            inline=False,
        )
    elif not key_found:
        embed.add_field(
            name="⚠️ Note",
            value="Could not find your key in today's activity. "
            "Your key alias may differ from the team record.",
            inline=False,
        )

    embed.set_footer(text=f"\U0001f4c5 Today — {today_str} (Bangkok)")

    return embed


# ── Error Message Helper ────────────────────────────────────────
def _error_message(status: int, context: str = "data") -> str:
    """Build a user-friendly error message from HTTP status code."""
    if status == 401:
        return ("🔐 **Authentication failed.** Your virtual key may be invalid or expired.\n"
                "Use **`/reset-key`** to update your key.")
    elif status == 404:
        return ("❌ Key not found. The virtual key may have been deleted.\n"
                "Use **`/reset-key`** to register a new key.")
    else:
        return (f"❌ Error fetching {context} (HTTP {status}).\n"
                "Use **`/reset-key`** to update your key.")


# ── Help Embed Builder ─────────────────────────────────────────
def build_help_embed(user: discord.User) -> discord.Embed:
    """Build the /help command embed."""
    embed = discord.Embed(
        title="🤖 LiteLLM Bot — Commands",
        description=(
            "Here are all available commands. **Click a button below** to run each "
            "command directly, or type the slash command in chat!"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Requested by {user}")

    embed.add_field(
        name="`/usage`",
        value="📊 Check your LiteLLM usage statistics (spend, models, rate limits, etc.)",
        inline=False,
    )
    embed.add_field(
        name="`/usage-daily`",
        value="🪙 Check today's usage dashboard (spend, tokens, requests)",
        inline=False,
    )
    embed.add_field(
        name="`/models`",
        value="🤖 List all AI models you have access to",
        inline=False,
    )
    embed.add_field(
        name="`/reset-key`",
        value="🔑 Reset / update your LiteLLM virtual key",
        inline=False,
    )
    embed.add_field(
        name="`/delete-key`",
        value="🗑️ Delete your data from the system",
        inline=False,
    )

    return embed


__all__ = [
    "format_usage_embed",
    "format_models_info_embed",
    "format_token_usage_embed",
    "_error_message",
    "build_help_embed",
]
