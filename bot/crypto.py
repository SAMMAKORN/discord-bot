"""Fernet-based encryption for virtual keys stored in SQLite."""

import base64
import os

from cryptography.fernet import Fernet, InvalidToken

# ── Key Management ──────────────────────────────────────────────
# Derive encryption key from environment variable.
# If ENCRYPTION_KEY is not set, generate one on first run and warn.

_KEY_FILE = ".encryption_key"


def _load_or_create_key() -> bytes:
    """Load encryption key from env var, key file, or generate new one."""
    env_key = os.getenv("ENCRYPTION_KEY")
    if env_key:
        # Accept raw base64 string (32 bytes)
        try:
            key = base64.urlsafe_b64decode(env_key)
            if len(key) == 32:
                return key
        except Exception:
            pass
        # Treat as plain text and derive
        return base64.urlsafe_b64encode(env_key.encode()[:32])

    key_path = _KEY_FILE
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read()

    # Auto-generate for convenience (not recommended for multi-instance deploy)
    print(f"[crypto] WARNING: No ENCRYPTION_KEY set. Auto-generated key stored at {key_path}")
    print("[crypto] For production, set ENCRYPTION_KEY env var and delete the key file.")
    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    return key


_FERNET: Fernet | None = None


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


# ── Public API ──────────────────────────────────────────────────
def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a URL-safe base64 token."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a previously encrypted token and return the original string."""
    return _get_fernet().decrypt(token.encode()).decode()


def reencrypt(old_token: str) -> str:
    """Re-encrypt a token that was encrypted with a different key.

    Useful when rotating the encryption key — decrypt with old key,
    encrypt with new key. Since we only keep one key, this simply
    re-encrypts with the current Fernet instance.
    """
    try:
        plain = decrypt(old_token)
    except InvalidToken:
        # Token was encrypted with old key — try to decrypt anyway
        # If it fails, the user needs to manually re-register their key
        print(f"[crypto] Could not decrypt token. Key may have rotated.")
        raise
    return encrypt(plain)
