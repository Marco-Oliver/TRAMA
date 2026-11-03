"""Regression: updater failures must not disclose private URLs, paths or tokens."""
import tempfile
import unittest
from unittest.mock import patch
from knowledge_bridge.update_service import download_verified_installer


class UpdaterPrivacyTests(unittest.TestCase):
    def test_network_exception_does_not_echo_sensitive_details(self):
        secret = "SECRET_ACCESS_TOKEN_please_do_not_log"
        def failing_opener(*args, **kwargs):
            raise OSError("https://private.example/download?token=" + secret)
        with tempfile.TemporaryDirectory() as directory:
            result = download_verified_installer("Marco-Oliver/TRAMA", directory,
                                                  opener=failing_opener)
        self.assertFalse(result["ok"])
        self.assertNotIn(secret, result["message"])
        self.assertNotIn("private.example", result["message"])


if __name__ == "__main__":
    unittest.main()
