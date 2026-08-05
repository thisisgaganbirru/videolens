import unittest

from app.security import quota_key_from_headers


class QuotaIdentityTests(unittest.TestCase):
    def test_uses_client_ip(self) -> None:
        key = quota_key_from_headers("", "203.0.113.7")
        self.assertEqual(key, "ip:203.0.113.7")

    def test_hashes_bearer_token(self) -> None:
        key = quota_key_from_headers("Bearer private-token", "203.0.113.7")
        self.assertTrue(key.startswith("token:"))
        self.assertNotIn("private-token", key)

    def test_bearer_token_takes_precedence_over_ip(self) -> None:
        key = quota_key_from_headers("Bearer private-token", "203.0.113.7")
        self.assertNotIn("203.0.113.7", key)

    def test_falls_back_to_anonymous_without_ip(self) -> None:
        self.assertEqual(quota_key_from_headers("", ""), "anonymous")


if __name__ == "__main__":
    unittest.main()
