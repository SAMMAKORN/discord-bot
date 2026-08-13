import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite
from cryptography.fernet import Fernet

from bot import crypto, db


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "bot.db"
        self.key = Fernet.generate_key().decode()
        self.environment = patch.dict(os.environ, {"ENCRYPTION_KEY": self.key}, clear=True)
        self.environment.start()
        crypto._FERNET = None
        db.configure(str(self.database_path))
        await db.init_db()

    async def asyncTearDown(self):
        await db.close_db()
        crypto._FERNET = None
        self.environment.stop()
        self.temp_directory.cleanup()

    async def test_crud_and_update_preserve_created_at(self):
        await db.save_user_key("42", "sk-first")
        async with aiosqlite.connect(self.database_path) as connection:
            first = await connection.execute_fetchall(
                "SELECT created_at FROM users WHERE user_id = ?", ("42",)
            )

        await db.save_user_key("42", "sk-second")
        async with aiosqlite.connect(self.database_path) as connection:
            second = await connection.execute_fetchall(
                "SELECT created_at FROM users WHERE user_id = ?", ("42",)
            )

        self.assertEqual(first[0][0], second[0][0])
        self.assertEqual(await db.get_user_key("42"), "sk-second")
        self.assertTrue(await db.has_user_key("42"))
        self.assertTrue(await db.delete_user_key("42"))
        self.assertFalse(await db.has_user_key("42"))

    async def test_wrong_key_raises_instead_of_returning_ciphertext(self):
        await db.save_user_key("42", "sk-secret")
        crypto._FERNET = Fernet(Fernet.generate_key())
        with self.assertRaises(db.KeyDecryptionError):
            await db.get_user_key("42")
