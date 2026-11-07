import unittest
from types import SimpleNamespace

from app.interface.api.rate_limiter import client_ip


class ClientIpTests(unittest.TestCase):
    def test_uses_the_entry_the_trusted_proxy_appended(self) -> None:
        # One trusted hop (the default): the client is the LAST entry, the one
        # the edge proxy wrote. The entries before it came from the client and
        # used to be what this read - a forged header then picked a fresh
        # rate-limit bucket per request.
        request = SimpleNamespace(
            headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_prefers_forwarded_for_over_the_peer(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-for": "203.0.113.7"},
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
