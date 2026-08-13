import unittest

from bot import api


class ApiTests(unittest.TestCase):
    def test_configure_removes_trailing_slash(self):
        api.configure("https://litellm.example///", "master")
        self.assertEqual(api.LITELLM_BASE_URL, "https://litellm.example")
        self.assertEqual(api.MASTER_KEY, "master")
