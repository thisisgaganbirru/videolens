import unittest

from app.infrastructure.config import Settings


class SettingsTests(unittest.TestCase):
    def test_default_origins_cover_local_frontend_ports(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(
            settings.allowed_origin_list,
            ["http://localhost:3000", "http://localhost:3005"],
        )

    def test_allowed_origins_are_split_and_trimmed(self) -> None:
        settings = Settings(
            _env_file=None,
            allowed_origins=" https://app.example.com, http://localhost:3005, ",
        )

        self.assertEqual(
            settings.allowed_origin_list,
            ["https://app.example.com", "http://localhost:3005"],
        )


if __name__ == "__main__":
    unittest.main()
