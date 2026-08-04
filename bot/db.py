"""Async SQLite database layer using aiosqlite."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .crypto import decrypt, encrypt

_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()
_db_open = False
_DB_PATH: str = "/app/data/bot.db"


def configure(db_path: str):
    """Set database path (called at bot startup)."""
    global _DB_PATH
    _DB_PATH = db_path


async def get_db() -> aiosqlite.Connection:
    """Return the shared aiosqlite connection, initializing if needed."""
    global _db, _db_open
    if _db is not None and _db_open:
        return _db

    async with _db_lock:
        if _db is not None and _db_open:
            return _db

        path = Path(_DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        _db = await aiosqlite.connect(str(path))
        _db.row_factory = aiosqlite.Row
        _db_open = True
        return _db


async def init_db():
    """Create the users table if it does not already exist.

    Migrate unencrypted keys to encrypted format on first connection.
    """
    conn = await get_db()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id     TEXT PRIMARY KEY,
                virtual_key TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            )
            """
        )
    await conn.commit()

    # Migrate legacy plaintext keys to encrypted format
    await _migrate_keys(conn)


async def _migrate_keys(conn: aiosqlite.Connection):
    """One-time migration: re-encrypt any plaintext keys in the database.

    Detection heuristic: encrypted tokens start with a long base64 segment
    and are typically >64 chars. LiteLLM keys usually start with 'sk-'.
    If a key starts with 'sk-', it's plaintext and needs encryption.
    """
    async with conn.cursor() as cur:
        await cur.execute("SELECT user_id, virtual_key FROM users")
        rows = await cur.fetchall()

        migrated = 0
        for row in rows:
            user_id: str = row["user_id"]
            virtual_key: str = row["virtual_key"]

            # Heuristic: plaintext keys start with 'sk-'
            if virtual_key.startswith("sk-"):
                encrypted = encrypt(virtual_key)
                now = datetime.now(timezone.utc).isoformat()
                await cur.execute(
                    "UPDATE users SET virtual_key = ?, updated_at = ? WHERE user_id = ?",
                    (encrypted, now, user_id),
                )
                migrated += 1

        if migrated > 0:
            await conn.commit()
            print(f"[db] Migrated {migrated} plaintext key(s) to encrypted format.")


async def close_db():
    """Close the shared database connection."""
    global _db, _db_open
    if _db is not None and _db_open:
        await _db.close()
        _db = None
        _db_open = False


# ── Public API ──────────────────────────────────────────────────
async def get_user_key(user_id: str) -> str | None:
    """Return the stored virtual key for *user_id*, or ``None``."""
    conn = await get_db()
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT virtual_key FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
    if row is None:
        return None
    encrypted = row["virtual_key"]
    try:
        return decrypt(encrypted)
    except Exception:
        # If decryption fails (key rotation), return the raw value
        # so the user can re-register
        print(f"[db] Decryption failed for user {user_id}. Key may have rotated.")
        return encrypted


async def save_user_key(user_id: str, virtual_key: str):
    """Insert or update the virtual key for *user_id* (encrypted at rest)."""
    now = datetime.now(timezone.utc).isoformat()
    encrypted = encrypt(virtual_key)
    conn = await get_db()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT OR REPLACE INTO users (user_id, virtual_key, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, encrypted, now, now),
        )
    await conn.commit()


async def delete_user_key(user_id: str) -> bool:
    """Delete the user's virtual key; return ``True`` if a row was removed."""
    conn = await get_db()
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM users WHERE user_id = ?", (user_id,)
        )
    await conn.commit()
    return cur.rowcount > 0
