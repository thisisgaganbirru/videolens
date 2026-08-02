import unittest

from app.security import quota_key_from_headers


class QuotaIdentityTests(unittest.TestCase):
    def test_uses_stable_client_identity(self) -> None:
        key = quota_key_from_headers("", "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(key, "client:12345678-1234-1234-1234-123456789abc")

    def test_hashes_bearer_token(self) -> None:
        key = quota_key_from_headers("Bearer private-token", "")
        self.assertTrue(key.startswith("token:"))
        self.assertNotIn("private-token", key)

    def test_rejects_short_client_identifier(self) -> None:
        self.assertEqual(quota_key_from_headers("", "short"), "anonymous")


if __name__ == "__main__":
    unittest.main()
