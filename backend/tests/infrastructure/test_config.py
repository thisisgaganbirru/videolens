import unittest

from app.infrastructure.config import NATIVE_APP_ORIGINS, Settings


class SettingsTests(unittest.TestCase):
    def test_default_origins_cover_local_frontend_ports(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(
            settings.allowed_origin_list,
            ["http://localhost:3000", "http://localhost:3005", *NATIVE_APP_ORIGINS],
        )

    def test_allowed_origins_are_split_and_trimmed(self) -> None:
        settings = Settings(
            _env_file=None,
            allowed_origins=" https://app.example.com, http://localhost:3005, ",
        )

        self.assertEqual(
            settings.allowed_origin_list,
            ["https://app.example.com", "http://localhost:3005", *NATIVE_APP_ORIGINS],
        )

    def test_native_app_origins_are_allowed_without_being_configured(self) -> None:
        """The Capacitor Android WebView calls the API from `https://localhost`.
        A deployment that only lists its web frontend must still accept the APK,
        or the preflight 400s and the app reports an unreachable server."""
        settings = Settings(_env_file=None, allowed_origins="https://app.example.com")

        self.assertIn("https://localhost", settings.allowed_origin_list)

    def test_native_app_origins_are_not_duplicated_when_configured(self) -> None:
        settings = Settings(
            _env_file=None,
            allowed_origins="https://localhost,https://app.example.com",
        )

        self.assertEqual(
            settings.allowed_origin_list.count("https://localhost"),
            1,
        )

    def test_native_app_origins_survive_an_empty_configuration(self) -> None:
        settings = Settings(_env_file=None, allowed_origins="")

        self.assertEqual(settings.allowed_origin_list, list(NATIVE_APP_ORIGINS))




class DistributedOriginTests(unittest.TestCase):
    """A CORS wildcard on a deployed (Redis-backed) API is refused at startup."""

    def test_wildcard_with_redis_is_refused(self) -> None:
        settings = Settings(_env_file=None, redis_url="redis://r:6379/0", allowed_origins="*")
        self.assertIn("ALLOWED_ORIGINS", settings.distributed_origin_error() or "")

    def test_wildcard_among_other_origins_is_still_refused(self) -> None:
        settings = Settings(
            _env_file=None, redis_url="redis://r:6379/0", allowed_origins="https://app.example.com, *"
        )
        self.assertIsNotNone(settings.distributed_origin_error())

    def test_real_origins_with_redis_are_fine(self) -> None:
        settings = Settings(_env_file=None, redis_url="redis://r:6379/0", allowed_origins="https://app.example.com")
        self.assertIsNone(settings.distributed_origin_error())

    def test_wildcard_without_redis_is_tolerated_for_local_runs(self) -> None:
        settings = Settings(_env_file=None, redis_url="", allowed_origins="*")
        self.assertIsNone(settings.distributed_origin_error())


if __name__ == "__main__":
    unittest.main()
