# LiteLLM Usage Discord Bot

A Discord bot for checking LiteLLM proxy usage and browsing available models via slash commands.

## Changelog

### v1.4.0 — Module Architecture, Async SQLite, and Encrypted Key Storage

#### Added
- **`bot/` package** — Monolith split into modular structure:
  - `bot/api.py` — LiteLLM proxy API client with shared `aiohttp.ClientSession`
  - `bot/db.py` — Async SQLite layer using `aiosqlite` (non-blocking)
  - `bot/crypto.py` — Fernet-based symmetric encryption for virtual keys at rest
  - `bot/embeds.py` — Discord embed formatters (usage, models, daily usage, help)
  - `bot/commands.py` — Slash commands, buttons, modals, views
- **Encrypted key storage** — Virtual keys are encrypted with Fernet (AES-128-CBC) before being written to SQLite. Decrypted on read. Auto-migrates legacy plaintext keys on first boot.
- **`ENCRYPTION_KEY` env var** — Optional. If set, uses the provided key for encryption. If omitted, auto-generates and stores locally (single-instance only).
- **Auto-migration** — On first boot, plaintext keys starting with `sk-` are automatically re-encrypted.
- **Comprehensive error handling** — All command handlers wrapped in try/except to prevent Discord "did not respond" errors.
- **`on_application_command_error`** — Global error handler for slash commands.

#### Changed
- **SQLite → aiosqlite** — All database calls are now async, eliminating event-loop blocking.
- **HTTP session pooling** — Shared `aiohttp.ClientSession` across all API calls instead of creating a new session per request.
- `aiosqlite` and `cryptography` added to `requirements.txt`.
- `.dockerignore` and `.gitignore` updated to exclude `.encryption_key`.
- Dockerfile updated to copy `bot/` package.
- `docker-compose.yml` updated with `ENCRYPTION_KEY` env var.

#### Fixed
- `interaction.response.send` → `interaction.response.send_message` (discord.py 2.x API).
- `BadRequest` → `HTTPException` (discord.py 2.x doesn't have `BadRequest`).
- UTF-8 stdout encoding on Windows (cp874 can't print emojis).

### v1.3.0 — Team API Migration, Key Alias Suffix Matching, and Robustness

#### Changed
- **Renamed `/usage-token` to `/usage-daily`** — the command now uses the team API (`/team/list` + `/team/daily/activity`) to display today's usage dashboard (total requests, tokens, spend, successful/failed breakdown, per-request averages) instead of showing all-time token consumption.
- Help command and button labels updated to reflect the new command name ("Daily Usage").
- **Team API migration** — `/usage-daily` resolves the user's key through `/team/list` to find the associated team, then queries `/team/daily/activity` for granular daily metrics.
- **Key alias suffix matching** — `_extract_key_metrics` falls back to matching the last 8 characters of the key alias when an exact match is not found.
- **Silent-zeros warning** — when `format_token_usage_embed` finds no activity data for the day, it adds a warning field.

#### Fixed
- **Latent bug in `_resolve_team_info`** — when `key_info["info"]` contained a `team_id` not present in the team list, the function now returns a result with `"team_alias": "Unknown"` and the known `team_id` instead of returning `None`.

### v1.2.3 — Bug Fixes

- Fixed model info fetch for `/models` command
- Improved error handling for API calls

### v1.2.2 — Rename `/usage-token` to `/usage-daily`

- Command renamed for clarity

### v1.2.1 — Add `/usage-token` Command

- Token usage statistics display

### v1.0.0 — Initial Release

- SQLite database for per-user virtual key storage
- Rich embed with key info, spend, rate limits, models, and config
- THB currency conversion using live exchange rate (exchangerate API)
- Asia/Bangkok timezone for Last Active timestamp
- Ephemeral responses for all commands
- Docker support (Dockerfile, docker-compose.yml)
- Coolify deployment guide
