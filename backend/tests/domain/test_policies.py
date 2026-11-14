import unittest
from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

from app.domain.entities import AuthMethod, Principal
from app.domain.policies import (
    can_access_run,
    client_ip_from_forwarded,
    looks_like_api_key,
    quota_key,
    quota_key_from_headers,
    seconds_until,
    seconds_until_next_utc_day,
)


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

    def test_bearer_scheme_is_case_insensitive(self) -> None:
        keys = {quota_key_from_headers(f"{scheme} private-token", "203.0.113.7") for scheme in ("Bearer", "bearer", "BEARER")}
        self.assertEqual(len(keys), 1)
        self.assertTrue(next(iter(keys)).startswith("token:"))

    def test_other_schemes_and_empty_bearers_use_the_ip(self) -> None:
        for header in ("Basic dXNlcjpwYXNz", "Bearer ", "Bearer"):
            with self.subTest(header=header):
                self.assertEqual(quota_key_from_headers(header, "203.0.113.7"), "ip:203.0.113.7")

    def test_falls_back_to_anonymous_without_ip(self) -> None:
        self.assertEqual(quota_key_from_headers("", ""), "anonymous")


class PrincipalQuotaKeyTests(unittest.TestCase):
    def test_anonymous_is_keyed_by_ip_never_by_client_id(self) -> None:
        anon = Principal(subject="client:abc0123456789xyz", authenticated=False)
        self.assertEqual(quota_key(anon, "203.0.113.7"), "ip:203.0.113.7")
        self.assertEqual(quota_key(anon, ""), "anonymous")

    def test_signed_in_person_is_keyed_by_account_not_token(self) -> None:
        person = Principal(subject="user:u1", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1")
        self.assertEqual(quota_key(person, "203.0.113.7"), "account:acct-1")

    def test_api_key_spends_from_the_owning_account(self) -> None:
        key = Principal(subject="key:k1", authenticated=True, method=AuthMethod.API_KEY, account_id="acct-1")
        self.assertEqual(quota_key(key, "203.0.113.7"), "account:acct-1")

    def test_token_without_an_account_store_falls_back_to_the_subject(self) -> None:
        person = Principal(subject="user:u1", authenticated=True, method=AuthMethod.TOKEN)
        self.assertEqual(quota_key(person, "203.0.113.7"), "user:u1")


class RunAccessTests(unittest.TestCase):
    def test_only_the_owner_sees_a_run(self) -> None:
        owner = Principal(subject="client:abc0123456789xyz", authenticated=False)
        other = Principal(subject="client:zzz0123456789xyz", authenticated=False)
        run = SimpleNamespace(owner_id="client:abc0123456789xyz")
        self.assertTrue(can_access_run(owner, run))
        self.assertFalse(can_access_run(other, run))
        self.assertFalse(can_access_run(owner, None))

    def test_signed_in_owner_is_matched_by_subject_in_this_phase(self) -> None:
        person = Principal(subject="user:u1", authenticated=True, method=AuthMethod.TOKEN, account_id="a", workspace_id="w")
        self.assertTrue(can_access_run(person, SimpleNamespace(owner_id="user:u1")))
        self.assertFalse(can_access_run(person, SimpleNamespace(owner_id="w")))


class ApiKeyShapeTests(unittest.TestCase):
    def test_recognises_the_prefix(self) -> None:
        self.assertTrue(looks_like_api_key("vl_live_abc"))
        self.assertFalse(looks_like_api_key("eyJhbGciOi.x.y"))
        self.assertFalse(looks_like_api_key(""))


class ForwardedClientIpTests(unittest.TestCase):
    """Which X-Forwarded-For entry is the caller, given how many proxies we
    own appended one. Pure, so every shape of header is cheap to pin down."""

    def test_one_trusted_hop_takes_the_last_entry(self) -> None:
        self.assertEqual(client_ip_from_forwarded("9.9.9.9, 203.0.113.7", "10.0.0.1", 1), "203.0.113.7")

    def test_forged_entries_on_the_left_are_ignored(self) -> None:
        self.assertEqual(
            client_ip_from_forwarded("evil-1, evil-2, evil-3, 203.0.113.7", "10.0.0.1", 1), "203.0.113.7"
        )

    def test_two_trusted_hops_take_the_second_from_the_end(self) -> None:
        # Client -> CDN -> edge: the edge appended the CDN's address last.
        self.assertEqual(client_ip_from_forwarded("203.0.113.7, 198.51.100.2", "10.0.0.1", 2), "203.0.113.7")

    def test_railway_shape_resolves_to_the_client_whatever_the_edge_hop(self) -> None:
        # Railway (measured 2026-11-07): "<client>, <edge hop>", the edge hop
        # varies per request. Two hops lands on the client every time; one hop
        # landed on the edge hop, a new rate-limit bucket per request.
        for edge_hop in ("152.233.40.1", "152.233.40.2"):
            self.assertEqual(client_ip_from_forwarded(f"203.0.113.50, {edge_hop}", "100.64.0.2", 2), "203.0.113.50")
            self.assertEqual(client_ip_from_forwarded(f"203.0.113.50, {edge_hop}", "100.64.0.2", 1), edge_hop)

    def test_fewer_entries_than_hops_falls_back_to_the_first(self) -> None:
        self.assertEqual(client_ip_from_forwarded("203.0.113.7", "10.0.0.1", 2), "203.0.113.7")

    def test_zero_hops_ignores_the_header(self) -> None:
        self.assertEqual(client_ip_from_forwarded("203.0.113.7", "198.51.100.9", 0), "198.51.100.9")

    def test_empty_header_uses_the_peer(self) -> None:
        self.assertEqual(client_ip_from_forwarded("", "198.51.100.9", 1), "198.51.100.9")
        self.assertEqual(client_ip_from_forwarded(" , ", "198.51.100.9", 1), "198.51.100.9")

    def test_whitespace_is_trimmed(self) -> None:
        self.assertEqual(client_ip_from_forwarded("  1.1.1.1 ,  203.0.113.7  ", "x", 1), "203.0.113.7")


class RetryAfterPolicyTests(unittest.TestCase):
    def test_counts_to_the_next_utc_midnight(self) -> None:
        now = datetime(2026, 11, 2, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(seconds_until_next_utc_day(now), 90 * 60)

    def test_rounds_a_partial_second_up(self) -> None:
        now = datetime(2026, 11, 2, 23, 59, 59, 500000, tzinfo=timezone.utc)
        self.assertEqual(seconds_until_next_utc_day(now), 1)

    def test_just_after_midnight_is_almost_a_full_day(self) -> None:
        now = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(seconds_until_next_utc_day(now), 86400)

    def test_converts_another_zone_to_utc_first(self) -> None:
        # 01:00 at +02:00 is 23:00 UTC the day before: one hour to go.
        now = datetime(2026, 11, 3, 1, 0, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(seconds_until_next_utc_day(now), 3600)

    def test_naive_datetimes_are_read_as_utc(self) -> None:
        self.assertEqual(seconds_until_next_utc_day(datetime(2026, 11, 2, 23, 0)), 3600)

    def test_seconds_until_rounds_up_and_never_reaches_zero(self) -> None:
        self.assertEqual(seconds_until(1000.2, 940.0), 61)
        self.assertEqual(seconds_until(1000.0, 1000.0), 1)
        self.assertEqual(seconds_until(900.0, 1000.0), 1)


if __name__ == "__main__":
    unittest.main()
