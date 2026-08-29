import unittest
from types import SimpleNamespace

from app.interface.api.rate_limiter import client_ip


class ClientIpTests(unittest.TestCase):
    def test_prefers_forwarded_for(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_falls_back_to_socket_peer_without_proxy_header(self) -> None:
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="198.51.100.9"))
        self.assertEqual(client_ip(request), "198.51.100.9")

    def test_handles_missing_client(self) -> None:
        request = SimpleNamespace(headers={}, client=None)
        self.assertEqual(client_ip(request), "")


if __name__ == "__main__":
    unittest.main()
