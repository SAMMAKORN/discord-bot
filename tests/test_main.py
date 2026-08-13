import unittest
from unittest.mock import patch

import main


class ConfigurationTests(unittest.TestCase):
    def test_missing_required_secrets_fail_fast(self):
        with (
            patch.object(main, "BOT_TOKEN", ""),
            patch.object(main, "MASTER_KEY", ""),
            self.assertRaisesRegex(RuntimeError, "BOT_TOKEN, MASTER_KEY"),
        ):
            main.validate_configuration()

    def test_invalid_base_url_fails_fast(self):
        with (
            patch.object(main, "BOT_TOKEN", "discord-token"),
            patch.object(main, "MASTER_KEY", "master-key"),
            patch.object(main, "LITELLM_BASE_URL", "not-a-url"),
            self.assertRaisesRegex(RuntimeError, "absolute HTTP"),
        ):
            main.validate_configuration()
