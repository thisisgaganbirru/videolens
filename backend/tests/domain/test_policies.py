import unittest
from datetime import datetime, timedelta, timezone

from app.domain.policies import quota_key_from_headers, seconds_until, seconds_until_next_utc_day


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
