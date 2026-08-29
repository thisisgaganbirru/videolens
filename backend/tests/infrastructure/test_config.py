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


if __name__ == "__main__":
    unittest.main()
