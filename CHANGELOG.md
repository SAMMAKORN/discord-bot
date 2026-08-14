# LiteLLM Usage Discord Bot

A Discord bot for checking LiteLLM proxy usage and browsing available models via slash commands.

## Changelog

### v1.5.1 — Dockerfile-only Coolify Deployment

#### Changed
- Coolify deployment now uses the **Dockerfile** build pack via **Git Repository (with GitHub App)** instead of the **Docker Compose** build pack.
- Removed `docker-compose.yml`; local development now uses plain `docker build` / `docker run` instead of `docker compose up`.
- Updated README deployment instructions accordingly, including configuring persistent storage (`/app/data`) directly in Coolify's Storages tab.
- Generalized the default `LITELLM_BASE_URL` fallback in `main.py` to a placeholder domain.

### v1.5.0 — Production Hardening

#### Fixed
- Correctly accept standard Fernet keys and validate encryption during startup.
- Persist Docker's generated key with private permissions inside `/app/data`.
- Never return encrypted database content as an API credential after key rotation.
- Paginate `/models` within Discord's field and total-character limits.
- Prefer the longest model pricing prefix to avoid incorrect cost metadata.
- Validate virtual keys before saving or replacing them.
- Remove the unused privileged Message Content intent.
- Normalize malformed/null LiteLLM fields and bound all embed content.
- Replace the `pgrep` healthcheck with a dependency-free SQLite check.

#### Added
- Thai response, button, modal, help, and command-description localization.
- Privacy notice before first-time key entry and disabled expired controls.
- Per-user throttling plus cached model metadata and exchange rates.
- Automated tests, pinned dependencies, linting, security checks, and CI.

### v1.4.1 — Embed Fixes and THB in `/usage-daily`

#### Fixed
- **`/models` double `$`** — Cost string was displaying `$ $15.00/$75.00`; now shows `$15.00/$75.00`.
- **`/models` truncated model names** — Short names like `qwen3.6-27b` were missing the provider prefix; now shows full names in backticks (e.g. `` `qwen/qwen3.6-27b` ``).
- **`/models` field name limit** — Provider names exceeding Discord's 60-character field name limit are now truncated.
- **`/models` compact mode** — No longer drops token and cost data; keeps per-model detail with smart truncation and `… and N more models` summary.
- **`/models` provider double-labeling** — Provider name now appears only in the embed field name, not redundantly in the field value.
- **`/models` invisible emoji** — Replaced `⚪` (white circle, invisible on light themes) with `🔵` for `"other"` and `🦙` for `"meta"` (Llama).
- **`/models` truncation boundary** — Hard truncation now cuts at a model entry boundary (newline) instead of mid-line.
- **`_format_short_num` rounding** — `500` displayed as `0K`; now uses `{val:g}` format (e.g. `1.28M`).

#### Added
- **`/usage-daily` THB display** — Spend field now shows both USD and THB (live exchange rate), matching `/usage`.

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

### v1.2.4 — Add `/usage-token` Command

- feat: add `/usage-token` command to display token usage statistics
- fix: normalize LiteLLM model names and expand provider prefix lookup
- fix: use LiteLLM admin `/models` endpoint for cost and capability data
- fix: correct cost display, dead variable, and modality icons in `/models`
- docs: sync `.env.example`, README, and `.dockerignore` with current code

### v1.2.3 — Bug Fixes

- Fixed model info fetch for `/models` command
- Improved error handling for API calls

### v1.2.2 — Rename `/usage-token` to `/usage-daily`

- Command renamed for clarity

### v1.2.1 — Add `/usage-token` Command

- Token usage statistics display

### v1.2.0 — `/models`, `/delete-key`, Interactive Help & Docker Fixes

- feat: add `/models` and `/delete-key` commands
- feat: improve help command with interactive buttons
- refactor: consolidate modals, add helpers, improve error handling
- fix: simplify bind mount to `./data` (remove unnecessary `COOLIFY_APP_DIR`)
- fix: use bind mount instead of named volume to persist DB across Coolify redeployments
- docs: add `DB_PATH` comment to `.env.example`, update README for new features

### v1.1.0 — Add `/models`, `/delete-key`, and Interactive Help

- feat: add `/models` command to browse available models
- feat: add `/delete-key` command to remove stored virtual keys
- feat: improve help command with interactive buttons
- docs: update README for new features

### v1.0.0 — Initial Release

- SQLite database for per-user virtual key storage
- Rich embed with key info, spend, rate limits, models, and config
- THB currency conversion using live exchange rate (exchangerate API)
- Asia/Bangkok timezone for Last Active timestamp
- Ephemeral responses for all commands
- Docker support (Dockerfile, docker-compose.yml)
- Coolify deployment guide
