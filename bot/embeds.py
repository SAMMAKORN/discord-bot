"""Discord embed formatters for all bot responses."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord

from .api import fetch_usd_thb_rate


def _truncate_key(key: str) -> str:
    """Mask a key while retaining a short suffix for identification."""
    if not key or key == "N/A":
        return "N/A"
    visible = key[-8:] if len(key) > 8 else key[-4:]
    return f"****{visible}"


def _safe_text(
    value: object,
    max_length: int = 1024,
    default: str = "N/A",
    *,
    escape: bool = True,
) -> str:
    """Return bounded text suitable for Discord embeds.

    Pass ``escape=False`` for titles, author names, and field names — Discord does
    not render markdown there, so escaping only leaks visible backslashes.
    """
    if value is None or value == "":
        return default
    result = str(value)
    if escape:
        result = discord.utils.escape_markdown(result, as_needed=True).replace("```", "` ` `")
    if len(result) <= max_length:
        return result
    return result[: max(0, max_length - 3)] + "..."


def _safe_number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_integer(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _format_timestamp(value: object, *, thai: bool = False) -> str:
    if value in (None, "", "N/A"):
        return "ไม่มีวันหมดอายุ" if thai else "No expiry"
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return f"<t:{int(parsed.timestamp())}:F>"
    except (TypeError, ValueError):
        return _safe_text(value, 100)


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
    "anthropic": "🟣",
    "openai": "🔵",
    "google": "🔴",
    "nvidia": "🟢",
    "qwen": "🟠",
    "mistral": "🟡",
    "amazon": "🔶",
    "meta": "🦙",
    "other": "🔵",
}


def _detect_provider(model_id: str) -> str:
    if "/" in model_id:
        return model_id.split("/")[0]
    lowered = model_id.lower()
    for provider, prefixes in _PROVIDER_HINTS.items():
        if any(lowered.startswith(prefix) for prefix in prefixes):
            return provider
    return "other"


def _format_short_num(number: int) -> str:
    if number >= 1_000_000:
        return f"{number / 1_000_000:g}M"
    if number >= 1_000:
        return f"{number / 1_000:g}K"
    return str(number)


def _lookup_model_info(pricing_data: dict, model_id: str) -> dict:
    """Match exact model names first, then the longest unambiguous prefix."""
    if not isinstance(pricing_data, dict):
        return {}
    if model_id in pricing_data and isinstance(pricing_data[model_id], dict):
        return pricing_data[model_id]

    short_name = model_id.split("/")[-1]
    candidates: list[tuple[int, dict]] = []
    for pricing_name, info in pricing_data.items():
        pricing_short_name = pricing_name.split("/")[-1]
        if not isinstance(info, dict):
            continue
        if short_name == pricing_short_name:
            return info
        if short_name.startswith(pricing_short_name) or pricing_short_name.startswith(short_name):
            candidates.append((len(pricing_short_name), info))
    return max(candidates, key=lambda item: item[0])[1] if candidates else {}


async def format_usage_embed(data: dict, *, thai: bool = False) -> discord.Embed:
    """Build the /usage embed with normalized fields and a live FX rate."""
    data = data if isinstance(data, dict) else {}
    info = data.get("info") or {}
    info = info if isinstance(info, dict) else {}
    key = str(data.get("key") or "N/A")
    spend = _safe_number(info.get("spend"))
    models = info.get("models") or []
    models = models if isinstance(models, list) else []
    config = info.get("config") or {}
    config = config if isinstance(config, dict) else {}

    try:
        usd_thb_rate = await fetch_usd_thb_rate()
    except Exception:  # External FX failure should not hide LiteLLM usage.
        usd_thb_rate = 0.0

    if usd_thb_rate > 0 and spend:
        spend_string = (
            f"${spend:,.2f} USD\n฿{spend * usd_thb_rate:,.2f} THB (1 USD = {usd_thb_rate:,.2f} THB)"
        )
    else:
        spend_string = f"${spend:,.2f} USD"

    embed = discord.Embed(
        title="📊 รายงานการใช้งาน LiteLLM" if thai else "📊 LiteLLM Usage Report",
        color=discord.Color.blurple(),
        timestamp=datetime.now(UTC),
    )
    embed.set_author(name=_safe_text(info.get("key_name"), 256, escape=False))
    embed.add_field(name="🔑 Virtual Key", value=f"```{_truncate_key(key)}```", inline=True)
    if info.get("key_alias") or data.get("key_alias"):
        embed.add_field(
            name="🏷️ ชื่อคีย์" if thai else "🏷️ Key Alias",
            value=_safe_text(info.get("key_alias") or data.get("key_alias"), 256),
            inline=True,
        )
    embed.add_field(
        name="💰 ค่าใช้จ่ายรวม" if thai else "💰 Total Spend",
        value=spend_string,
        inline=False,
    )
    embed.add_field(
        name="📅 วันหมดอายุ" if thai else "📅 Expires",
        value=_format_timestamp(info.get("expires"), thai=thai),
        inline=True,
    )

    last_active = info.get("last_active")
    if last_active:
        try:
            parsed = datetime.fromisoformat(str(last_active))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            last_active_string = (
                f"<t:{int(parsed.timestamp())}:F> · <t:{int(parsed.timestamp())}:R>"
            )
        except (TypeError, ValueError):
            last_active_string = _safe_text(last_active, 100)
        embed.add_field(
            name="🕐 ใช้งานล่าสุด" if thai else "🕐 Last Active",
            value=last_active_string,
            inline=True,
        )

    rate_parts = []
    rate_fields = (
        # LiteLLM /key/info reports "rpm_limit"; "rpm_requests" never existed and
        # silently hid the request-per-minute limit.
        ("rpm_limit", "req/min"),
        ("tpm_limit", "tok/min"),
        ("max_parallel_requests", "parallel"),
    )
    for key_name, label in rate_fields:
        if info.get(key_name) is not None:
            rate_parts.append(f"{_safe_integer(info[key_name]):,} {label}")
    if rate_parts:
        embed.add_field(
            name="⚡ ขีดจำกัด" if thai else "⚡ Rate Limits",
            value=", ".join(rate_parts),
            inline=True,
        )

    if info.get("max_budget") is not None:
        embed.add_field(
            name="💵 งบประมาณสูงสุด" if thai else "💵 Max Budget",
            value=f"${_safe_number(info['max_budget']):,.2f}",
            inline=True,
        )

    model_text = (
        ", ".join(str(model) for model in models)
        if models
        else ("ทุกโมเดล" if thai else "All models")
    )
    embed.add_field(
        name="🤖 โมเดล" if thai else "🤖 Models",
        value=_safe_text(model_text, 500),
        inline=True,
    )

    if config:
        config_text = "\n".join(f"{key}: {value}" for key, value in config.items())
        embed.add_field(
            name="⚙️ การตั้งค่า" if thai else "⚙️ Config",
            value=f"```{_safe_text(config_text, 1014)}```",
            inline=False,
        )
    return embed


def _empty_models_embed(message: str, *, thai: bool = False) -> discord.Embed:
    return discord.Embed(
        title="🤖 โมเดลที่ใช้งานได้" if thai else "🤖 Available Models",
        description=message,
        color=discord.Color.gold(),
        timestamp=datetime.now(UTC),
    )


def format_models_info_embeds(
    models_resp: dict,
    pricing_data: dict,
    *,
    thai: bool = False,
) -> list[discord.Embed]:
    """Build model pages respecting 25-field and 6,000-character limits."""
    model_list = models_resp.get("data", []) if isinstance(models_resp, dict) else []
    if not isinstance(model_list, list) or not model_list:
        return [
            _empty_models_embed(
                (
                    "คีย์นี้ยังไม่มีโมเดล กรุณาตรวจสอบคีย์ ติดต่อผู้ดูแล LiteLLM หรือลองใหม่ภายหลัง"
                    if thai
                    else "No models are assigned to this key. Check the key, contact your "
                    "LiteLLM administrator, or try again later."
                ),
                thai=thai,
            )
        ]

    rows: list[dict] = []
    for model in model_list:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id") or model.get("model") or "unknown")
        info = _lookup_model_info(pricing_data, model_id)
        rows.append(
            {
                "provider": _detect_provider(model_id),
                "name": model_id,
                "max_input": _safe_integer(info.get("max_input_tokens")),
                "max_output": _safe_integer(info.get("max_output_tokens")),
                "price_input": info.get("input_cost_per_token"),
                "price_output": info.get("output_cost_per_token"),
            }
        )
    if not rows:
        return [
            _empty_models_embed(
                "ไม่พบข้อมูลโมเดลที่ใช้ได้ กรุณาลองใหม่ภายหลัง"
                if thai
                else "No valid model records were returned. Please try again later.",
                thai=thai,
            )
        ]

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["provider"], []).append(row)

    def format_cost(row: dict) -> str:
        input_price = row["price_input"]
        output_price = row["price_output"]
        if input_price is None and output_price is None:
            return "N/A"
        input_string = (
            f"${_safe_number(input_price) * 1_000_000:.2f}" if input_price is not None else "—"
        )
        output_string = (
            f"${_safe_number(output_price) * 1_000_000:.2f}" if output_price is not None else "—"
        )
        return (
            f"{input_string} อินพุต · {output_string} เอาต์พุต"
            if thai
            else f"{input_string} input · {output_string} output"
        )

    field_specs: list[tuple[str, str]] = []
    for provider, provider_rows in sorted(groups.items()):
        base_name = _safe_text(
            f"{_PROVIDER_EMOJI.get(provider, '🔵')} {provider}", 230, escape=False
        )
        lines = []
        for row in provider_rows:
            model_name = _safe_text(row["name"], 350)
            input_tokens = _format_short_num(row["max_input"]) if row["max_input"] else "—"
            output_tokens = _format_short_num(row["max_output"]) if row["max_output"] else "—"
            lines.append(
                f"• `{model_name}`\n"
                f"  **{'อินพุต' if thai else 'Input'}:** {input_tokens} · "
                f"**{'เอาต์พุต' if thai else 'Output'}:** {output_tokens}\n"
                f"  **{'ราคาต่อ 1M' if thai else 'Price/1M'}:** {format_cost(row)}"
            )

        chunk: list[str] = []
        chunk_length = 0
        chunk_number = 1
        for line in lines:
            added_length = len(line) + (1 if chunk else 0)
            if chunk and chunk_length + added_length > 1000:
                continuation = "ต่อ" if thai else "cont."
                name = (
                    base_name
                    if chunk_number == 1
                    else f"{base_name} ({continuation} {chunk_number})"
                )
                field_specs.append((_safe_text(name, 256, escape=False), "\n".join(chunk)))
                chunk = []
                chunk_length = 0
                chunk_number += 1
            chunk.append(line)
            chunk_length += len(line) + (1 if len(chunk) > 1 else 0)
        if chunk:
            continuation = "ต่อ" if thai else "cont."
            name = (
                base_name if chunk_number == 1 else f"{base_name} ({continuation} {chunk_number})"
            )
            field_specs.append((_safe_text(name, 256, escape=False), "\n".join(chunk)))

    packed_pages: list[list[tuple[str, str]]] = [[]]
    page_characters = 200
    for name, value in field_specs:
        field_characters = len(name) + len(value)
        if packed_pages[-1] and (
            len(packed_pages[-1]) >= 25 or page_characters + field_characters > 5400
        ):
            packed_pages.append([])
            page_characters = 200
        packed_pages[-1].append((name, value))
        page_characters += field_characters

    total = len(rows)
    provider_count = len(groups)
    page_count = len(packed_pages)
    embeds = []
    for index, fields in enumerate(packed_pages, start=1):
        page = discord.Embed(
            title="🤖 โมเดลที่ใช้งานได้" if thai else "🤖 Available Models",
            description=(
                f"**{total}** model(s) across **{provider_count}** provider(s) · "
                f"Page {index}/{page_count}"
                if not thai
                else f"**{total}** โมเดล จาก **{provider_count}** provider · "
                f"หน้า {index}/{page_count}"
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(UTC),
        )
        for name, value in fields:
            page.add_field(name=name, value=value, inline=False)
        embeds.append(page)
    return embeds


def format_models_info_embed(
    models_resp: dict,
    pricing_data: dict,
    *,
    thai: bool = False,
) -> discord.Embed:
    """Backward-compatible single-page formatter."""
    return format_models_info_embeds(models_resp, pricing_data, thai=thai)[0]


def _extract_key_metrics(results: list[dict], key_alias: str) -> tuple[dict, bool]:
    """Sum metrics for an exact key alias across activity results."""
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
    for day in results:
        if not isinstance(day, dict):
            continue
        breakdown = day.get("breakdown") or {}
        api_keys = breakdown.get("api_keys") or {} if isinstance(breakdown, dict) else {}
        if not isinstance(api_keys, dict):
            continue
        for key_info in api_keys.values():
            if not isinstance(key_info, dict):
                continue
            metadata = key_info.get("metadata") or {}
            remote_alias = metadata.get("key_alias", "") if isinstance(metadata, dict) else ""
            if remote_alias != key_alias:
                continue
            metrics = key_info.get("metrics") or {}
            if isinstance(metrics, dict):
                for metric, value in metrics.items():
                    if metric in totals and isinstance(value, (int, float)):
                        totals[metric] += value
            found = True
    return totals, found


def _resolve_team_info(key_info: dict) -> dict | None:
    key_info = key_info if isinstance(key_info, dict) else {}
    info = key_info.get("info", {}) or {}
    info = info if isinstance(info, dict) else {}
    team_id = info.get("team_id")
    if team_id:
        return {
            # /key/info does not return team_alias; the caller resolves it via
            # api.fetch_team_alias() and overwrites this fallback.
            "team_alias": info.get("team_alias") or "Unknown",
            "team_id": team_id,
            "key_alias": info.get("key_alias") or info.get("key_name", "Unknown"),
        }
    return None


async def format_token_usage_embed(
    team_info: dict,
    activity: dict,
    *,
    thai: bool = False,
) -> discord.Embed:
    """Format today's token usage stats for the user's key."""
    # Match on the raw alias — _safe_text escapes markdown and truncates, which
    # would never compare equal to the alias LiteLLM reports in the activity feed.
    raw_key_alias = str(team_info.get("key_alias") or "Unknown")
    team_alias = _safe_text(team_info.get("team_alias"), 100, "Unknown", escape=False)
    key_alias = _safe_text(raw_key_alias, 100, "Unknown", escape=False)
    results = activity.get("results", []) if isinstance(activity, dict) else []
    results = results if isinstance(results, list) else []
    metrics, key_found = _extract_key_metrics(results, raw_key_alias)

    successful = metrics["successful_requests"]
    failed = metrics["failed_requests"]
    requests = metrics["api_requests"] or successful + failed
    tokens = metrics["total_tokens"]
    spend = metrics["spend"]
    average_tokens = tokens // requests if requests > 0 else 0
    average_spend = spend / requests if requests > 0 else 0.0

    try:
        usd_thb_rate = await fetch_usd_thb_rate()
    except Exception:  # External FX failure should not hide usage.
        usd_thb_rate = 0.0
    spend_string = f"${spend:,.2f} USD"
    if usd_thb_rate > 0 and spend:
        spend_string += f"\n฿{spend * usd_thb_rate:,.2f} THB"

    today = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d")
    embed = discord.Embed(
        title=f"{key_alias} ({'ทีม' if thai else 'team'}: {team_alias})",
        color=discord.Color.blurple() if key_found else discord.Color.dark_gold(),
        timestamp=datetime.now(UTC),
    )
    fields = (
        ("📊 **คำขอทั้งหมด**" if thai else "📊 **Total Requests**", f"`{requests:,}`"),
        ("🦙 **โทเคนทั้งหมด**" if thai else "🦙 **Total Tokens**", f"`{tokens:,}`"),
        ("💰 **ค่าใช้จ่ายรวม**" if thai else "💰 **Total Spend**", spend_string),
        ("✅ **สำเร็จ**" if thai else "✅ **Successful**", f"`{successful:,}`"),
        ("❌ **ล้มเหลว**" if thai else "❌ **Failed**", f"`{failed:,}`"),
        (
            "⚡ **เฉลี่ย/คำขอ**" if thai else "⚡ **Avg/request**",
            f"`{average_tokens:,}` tok\n`${average_spend:,.4f}`",
        ),
    )
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=True)

    if not key_found:
        if thai:
            note = (
                "วันนี้ยังไม่พบข้อมูลการใช้งาน ระบบจึงแสดงค่าเป็นศูนย์"
                if not results
                else "ไม่พบชื่อคีย์ที่ตรงกันในข้อมูลวันนี้ จึงไม่นำข้อมูลระดับทีมมาแสดงแทน"
            )
        else:
            note = (
                "No activity data was found for today. The dashboard shows zeroes."
                if not results
                else "Your exact key alias was not found in today's activity; no team data was attributed to it."
            )
        embed.add_field(name="⚠️ หมายเหตุ" if thai else "⚠️ Note", value=note, inline=False)
    embed.set_footer(text=f"📅 {'วันนี้' if thai else 'Today'} — {today} (Asia/Bangkok)")
    return embed


def _error_message(
    status: int,
    context: str = "data",
    *,
    thai: bool = False,
    user_credential: bool = True,
) -> str:
    """Build a localized, actionable HTTP error message."""
    if status in (401, 403) and user_credential:
        return (
            "🔐 คีย์ไม่ถูกต้องหรือหมดอายุ ใช้ **`/reset-key`** เพื่อลงทะเบียนใหม่"
            if thai
            else "🔐 **Authentication failed.** Use **`/reset-key`** to update your key."
        )
    if status == 404 and user_credential:
        return (
            "❌ ไม่พบคีย์นี้ ใช้ **`/reset-key`** เพื่อลงทะเบียนใหม่"
            if thai
            else "❌ Key not found. Use **`/reset-key`** to register a new key."
        )
    if status == 429:
        return (
            "⏳ มีคำขอมากเกินไป กรุณารอสักครู่แล้วลองใหม่"
            if thai
            else "⏳ Too many requests. Please wait a moment and try again."
        )
    if status >= 500 or (status in (401, 403) and not user_credential):
        return (
            "🛠️ บริการต้นทางมีปัญหา กรุณาลองใหม่ภายหลังหรือติดต่อผู้ดูแล"
            if thai
            else "🛠️ The upstream service is unavailable. Try later or contact an administrator."
        )
    return (
        f"❌ ดึงข้อมูล {context} ไม่สำเร็จ (HTTP {status}) กรุณาลองใหม่"
        if thai
        else f"❌ Could not fetch {context} (HTTP {status}). Please try again."
    )


def build_help_embed(user: discord.User, *, thai: bool = False) -> discord.Embed:
    """Build the localized /help command embed."""
    embed = discord.Embed(
        title="🤖 คำสั่ง LiteLLM Bot" if thai else "🤖 LiteLLM Bot — Commands",
        description=(
            "กดปุ่มด้านล่างหรือพิมพ์ slash command ได้โดยตรง"
            if thai
            else "Click a button below or type a slash command to get started."
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.now(UTC),
    )
    embed.set_footer(text=f"{'เรียกโดย' if thai else 'Requested by'} {user}")
    fields = (
        (
            "`/usage`",
            "📊 ดูยอดใช้จ่าย โมเดล และ rate limits",
            "📊 View spend, models, and rate limits",
        ),
        (
            "`/usage-daily`",
            "🪙 ดู spend, tokens และ requests ของวันนี้",
            "🪙 View today's spend, tokens, and requests",
        ),
        ("`/models`", "🤖 ดูโมเดล AI ที่คีย์ของคุณใช้งานได้", "🤖 List models available to your key"),
        ("`/reset-key`", "🔑 เปลี่ยน LiteLLM virtual key", "🔑 Change your LiteLLM virtual key"),
        ("`/delete-key`", "🗑️ ลบคีย์และข้อมูลของคุณ", "🗑️ Delete your key and stored data"),
    )
    for name, thai_value, english_value in fields:
        embed.add_field(name=name, value=thai_value if thai else english_value, inline=False)
    return embed


__all__ = [
    "_error_message",
    "build_help_embed",
    "format_models_info_embed",
    "format_models_info_embeds",
    "format_token_usage_embed",
    "format_usage_embed",
]
