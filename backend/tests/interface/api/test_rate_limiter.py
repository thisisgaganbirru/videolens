import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from app.infrastructure.config import Settings
from app.interface.api import rate_limiter
from app.domain.entities import AuthMethod, Principal
from app.interface.api.rate_limiter import client_ip, quota_key

# Header shapes measured on Railway's dev environment (2026-11-07) with an
# opt-in diagnostic. The edge REPLACES X-Forwarded-For with
# "<client>, <edge hop>" (a client-sent value never arrives), the edge hop
# varies per request, X-Real-IP is overwritten with the client, and the
# socket peer is a different 100.64.0.x on every request.
CLIENT = "203.0.113.50"


def railway_request(edge_hop: str, peer: str, **extra: str) -> SimpleNamespace:
    headers = {"x-forwarded-for": f"{CLIENT}, {edge_hop}", "x-real-ip": CLIENT}
    headers.update(extra)
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


class ClientIpTests(unittest.TestCase):
    def setUp(self) -> None:
        # The code default, independent of any local .env.
        patcher = mock.patch.object(rate_limiter.settings, "trusted_proxy_hops", Settings.model_fields["trusted_proxy_hops"].default)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_hops_match_railway(self) -> None:
        self.assertEqual(Settings.model_fields["trusted_proxy_hops"].default, 2)

    def test_railway_requests_from_one_client_share_one_ip(self) -> None:
        # The last entry and the peer vary; the client entry does not. Keying
        # on the last entry (the old default of 1) gave every request its own
        # rate-limit bucket, so no per-IP limit ever tripped on Railway.
        ips = {
            client_ip(railway_request("152.233.40.1", "100.64.0.2")),
            client_ip(railway_request("152.233.40.2", "100.64.0.5")),
            client_ip(railway_request("152.233.40.7", "100.64.0.9")),
        }
        self.assertEqual(ips, {CLIENT})

    def test_forged_headers_do_not_reach_the_key_on_railway(self) -> None:
        # What arrived when the client sent X-Forwarded-For: 198.51.100.7,
        # X-Real-IP: 198.51.100.8, Forwarded and X-Envoy-External-Address:
        # the edge dropped the first two; the last two pass through but are
        # never read.
        request = railway_request(
            "152.233.40.2",
            "100.64.0.6",
            forwarded="for=198.51.100.10",
            **{"x-envoy-external-address": "198.51.100.11"},
        )
        self.assertEqual(client_ip(request), CLIENT)

    def test_entries_a_client_prepends_are_ignored(self) -> None:
        # Railway replaces the header today; if an edge ever appended instead,
        # a forged entry would sit further left and still not be read.
        request = SimpleNamespace(
            headers={"x-forwarded-for": f"198.51.100.7, {CLIENT}, 152.233.40.1"},
            client=SimpleNamespace(host="100.64.0.2"),
        )
        self.assertEqual(client_ip(request), CLIENT)

    def test_one_hop_platform_uses_the_last_entry(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},
            client=SimpleNamespace(host="10.0.0.1"),
        )
        with mock.patch.object(rate_limiter.settings, "trusted_proxy_hops", 1):
            self.assertEqual(client_ip(request), "203.0.113.7")

    def test_falls_back_to_socket_peer_without_proxy_header(self) -> None:
        # Local, docker compose and direct runs: no proxy, no header.
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="198.51.100.9"))
        self.assertEqual(client_ip(request), "198.51.100.9")

    def test_handles_missing_client(self) -> None:
        request = SimpleNamespace(headers={}, client=None)
        self.assertEqual(client_ip(request), "")


class ReadLimitAcrossRunIdsTests(unittest.TestCase):
    """GET /api/runs/{run_id} shares one bucket per caller across run ids.

    slowapi's default key_style ("url") bucketed by path, so polling a fresh
    random id per request never tripped READ_RATE_LIMIT_PER_MINUTE. On Railway
    that hid behind the X-Forwarded-For bug above; both were measured there.
    """

    def setUp(self) -> None:
        from starlette.testclient import TestClient

        from app.interface.api.app import app

        rate_limiter.limiter.reset()
        self.addCleanup(rate_limiter.limiter.reset)
        patcher = mock.patch.object(rate_limiter.settings, "trusted_proxy_hops", 2)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def test_cycling_run_ids_and_edge_hops_still_trips_the_limit(self) -> None:
        from app.interface.api.routes import container

        limit = container.settings.read_rate_limit_per_minute
        codes = []
        for i in range(limit + 1):
            response = self.client.get(
                f"/api/runs/{uuid.uuid4().hex}",
                headers={
                    "X-Client-ID": "test-client-0123456789",
                    # Railway's shape: varying edge hop, client entry stable.
                    "X-Forwarded-For": f"{CLIENT}, 152.233.40.{i % 5 + 1}",
                    "X-Real-IP": CLIENT,
                },
            )
            codes.append(response.status_code)
        self.assertNotIn(429, codes[:limit])
        self.assertEqual(codes[limit], 429)



class QuotaKeyFromPrincipalTests(unittest.TestCase):
    """The bucket follows the caller `get_principal` resolved, not the raw
    token, so a signed-in person keeps one bucket across token refreshes."""

    def _request(self, principal=None, authorization: str = "") -> SimpleNamespace:
        headers = {"x-forwarded-for": f"{CLIENT}, 10.0.0.1"}
        if authorization:
            headers["authorization"] = authorization
        state = SimpleNamespace(principal=principal) if principal is not None else SimpleNamespace()
        return SimpleNamespace(headers=headers, client=SimpleNamespace(host="100.64.0.2"), state=state)

    def test_a_person_keeps_one_bucket_across_token_refreshes(self) -> None:
        person = Principal(subject="user:u1", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1")
        keys = {
            quota_key(self._request(person, "Bearer first-token")),
            quota_key(self._request(person, "Bearer refreshed-token")),
        }
        self.assertEqual(keys, {"account:acct-1"})

    def test_an_api_key_shares_its_owners_bucket(self) -> None:
        key = Principal(subject="key:k1", authenticated=True, method=AuthMethod.API_KEY, account_id="acct-1")
        self.assertEqual(quota_key(self._request(key, "Bearer vl_live_x")), "account:acct-1")

    def test_anonymous_is_keyed_by_ip(self) -> None:
        anon = Principal(subject="client:abc0123456789xyz", authenticated=False)
        self.assertEqual(quota_key(self._request(anon)), f"ip:{CLIENT}")

    def test_unresolved_request_falls_back_to_the_header_key(self) -> None:
        key = quota_key(self._request(None, "Bearer private-token"))
        self.assertTrue(key.startswith("token:"))
        self.assertNotIn("private-token", key)
        self.assertEqual(quota_key(self._request(None)), f"ip:{CLIENT}")

if __name__ == "__main__":
    unittest.main()
