import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from bot import crypto


class CryptoTests(unittest.TestCase):
    def tearDown(self):
        crypto._FERNET = None

    def test_generated_fernet_environment_key_round_trips(self):
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": key}, clear=True):
            crypto._FERNET = None
            token = crypto.encrypt("sk-secret")
            self.assertEqual(crypto.decrypt(token), "sk-secret")

    def test_malformed_environment_key_fails(self):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "short"}, clear=True):
            crypto._FERNET = None
            with self.assertRaisesRegex(ValueError, "Fernet.generate_key"):
                crypto.initialize()

    def test_legacy_32_character_passphrase_remains_readable(self):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": "a" * 32}, clear=True):
            crypto._FERNET = None
            token = crypto.encrypt("sk-legacy")
            crypto._FERNET = None
            self.assertEqual(crypto.decrypt(token), "sk-legacy")

    def test_generated_key_file_is_private_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "nested" / ".encryption_key"
            environment = {"ENCRYPTION_KEY_FILE": str(key_file)}
            with patch.dict(os.environ, environment, clear=True):
                crypto._FERNET = None
                first_token = crypto.encrypt("sk-secret")
                self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)

                crypto._FERNET = None
                self.assertEqual(crypto.decrypt(first_token), "sk-secret")
