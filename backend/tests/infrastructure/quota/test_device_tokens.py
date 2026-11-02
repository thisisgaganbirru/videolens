import unittest

from app.infrastructure.config import Settings
from app.infrastructure.quota.device_tokens import HmacDeviceTokens


class HmacDeviceTokensTests(unittest.TestCase):
    def _tokens(self, **overrides) -> HmacDeviceTokens:
        return HmacDeviceTokens(Settings(_env_file=None, device_token_secret="s3cret-for-tests", **overrides))

    def test_an_issued_token_verifies_to_its_device_id(self) -> None:
        tokens = self._tokens()
        token = tokens.issue()
        device_id, _, _ = token.partition(".")
        self.assertEqual(tokens.verify(token), device_id)

    def test_every_issued_token_is_a_new_device(self) -> None:
        tokens = self._tokens()
        self.assertNotEqual(tokens.verify(tokens.issue()), tokens.verify(tokens.issue()))

    def test_a_tampered_signature_is_rejected(self) -> None:
        tokens = self._tokens()
        device_id, _, signature = tokens.issue().partition(".")
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
        self.assertIsNone(tokens.verify(f"{device_id}.{flipped}"))

    def test_a_swapped_device_id_is_rejected(self) -> None:
        tokens = self._tokens()
        _, _, signature = tokens.issue().partition(".")
        self.assertIsNone(tokens.verify(f"AAAAAAAAAAAAAAAAAAAAAA.{signature}"))

    def test_a_token_signed_with_another_secret_is_rejected(self) -> None:
        other = HmacDeviceTokens(Settings(_env_file=None, device_token_secret="different"))
        self.assertIsNone(self._tokens().verify(other.issue()))

    def test_replicas_sharing_a_secret_accept_each_others_tokens(self) -> None:
        self.assertIsNotNone(self._tokens().verify(self._tokens().issue()))

    def test_garbage_is_rejected(self) -> None:
        tokens = self._tokens()
        for value in ("", "no-dot", ".", "short.sig", "x" * 300, "a b c d e f g h i j.sig"):
            with self.subTest(value=value):
                self.assertIsNone(tokens.verify(value))


class DeviceTokenStartupTests(unittest.TestCase):
    def test_distributed_mode_without_a_secret_fails_at_startup(self) -> None:
        tokens = HmacDeviceTokens(Settings(_env_file=None, redis_url="redis://r:6379/0"))
        with self.assertRaisesRegex(RuntimeError, "DEVICE_TOKEN_SECRET"):
            tokens.validate_configuration()

    def test_distributed_mode_with_a_secret_starts(self) -> None:
        tokens = HmacDeviceTokens(
            Settings(_env_file=None, redis_url="redis://r:6379/0", device_token_secret="set")
        )
        tokens.validate_configuration()

    def test_distributed_mode_with_free_runs_off_needs_no_secret(self) -> None:
        tokens = HmacDeviceTokens(
            Settings(_env_file=None, redis_url="redis://r:6379/0", free_runs_per_device=0)
        )
        tokens.validate_configuration()

    def test_local_mode_without_a_secret_warns_and_still_works(self) -> None:
        tokens = HmacDeviceTokens(Settings(_env_file=None))
        with self.assertLogs("videolens", level="WARNING"):
            tokens.validate_configuration()
        self.assertIsNotNone(tokens.verify(tokens.issue()))


if __name__ == "__main__":
    unittest.main()
