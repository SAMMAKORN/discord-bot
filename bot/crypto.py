"""Fernet-based encryption for virtual keys stored in SQLite."""

import base64
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet

_DEFAULT_KEY_FILE = ".encryption_key"
_FERNET: Fernet | None = None
logger = logging.getLogger(__name__)


def _validate_key(key: bytes, source: str) -> bytes:
    """Validate and return a Fernet key without decoding it first."""
    try:
        Fernet(key)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{source} must be a Fernet.generate_key() value (32 url-safe base64-encoded bytes)."
        ) from exc
    return key


def _key_file_path() -> Path:
    return Path(os.getenv("ENCRYPTION_KEY_FILE", _DEFAULT_KEY_FILE))


def _load_or_create_key() -> bytes:
    """Load a validated key from the environment/file, or create it securely."""
    env_key = os.getenv("ENCRYPTION_KEY", "").strip()
    if env_key:
        try:
            encoded_key = env_key.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("ENCRYPTION_KEY must contain ASCII characters only.") from exc
        try:
            return _validate_key(encoded_key, "ENCRYPTION_KEY")
        except ValueError:
            if len(encoded_key) == 32:
                logger.warning(
                    "ENCRYPTION_KEY uses the deprecated 32-character passphrase format; "
                    "rotate to a Fernet.generate_key() value"
                )
                return base64.urlsafe_b64encode(encoded_key)
            raise

    key_path = _key_file_path()
    if key_path.exists():
        key = _validate_key(key_path.read_bytes().strip(), str(key_path))
        key_path.chmod(0o600)
        return key

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        file_descriptor = os.open(
            key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return _validate_key(key_path.read_bytes().strip(), str(key_path))

    with os.fdopen(file_descriptor, "wb") as key_file:
        key_file.write(key)

    logger.warning(
        "ENCRYPTION_KEY is not set; generated a persistent key at %s",
        key_path,
    )
    return key


def initialize() -> None:
    """Load and validate encryption configuration during startup."""
    _get_fernet()


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a URL-safe base64 token."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a previously encrypted token and return the original string."""
    return _get_fernet().decrypt(token.encode()).decode()
