import unittest

from pydantic import ValidationError

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


class DistributedDatabaseTests(unittest.TestCase):
    """A SQLite identity store on a deployed (Redis-backed) API is refused at
    startup: per-replica files would break API keys across replicas."""

    def test_sqlite_with_redis_is_refused(self) -> None:
        for url in ("sqlite:///./ids.sqlite3", "sqlite+aiosqlite:///./ids.sqlite3", "SQLite://"):
            with self.subTest(url=url):
                settings = Settings(_env_file=None, redis_url="redis://r:6379/0", database_url=url)
                self.assertIn("DATABASE_URL", settings.distributed_database_error() or "")

    def test_postgres_or_blank_with_redis_is_fine(self) -> None:
        for url in ("", "postgresql://u:p@h:6543/postgres", "postgres://u:p@h/db"):
            with self.subTest(url=url):
                settings = Settings(_env_file=None, redis_url="redis://r:6379/0", database_url=url)
                self.assertIsNone(settings.distributed_database_error())

    def test_sqlite_without_redis_is_tolerated_for_local_runs(self) -> None:
        settings = Settings(_env_file=None, redis_url="", database_url="sqlite:///./ids.sqlite3")
        self.assertIsNone(settings.distributed_database_error())


class GeminiVideoSettingsTests(unittest.TestCase):
    def test_defaults_leave_gemini_on_its_own_defaults(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual(settings.gemini_video_fps, 0.0)
        self.assertEqual(settings.gemini_media_resolution, "")

    def test_fps_is_off_or_between_half_and_two(self) -> None:
        for fps in (-1.0, 0.1, 0.49, 2.01, 3.0, 24.0):
            with self.subTest(fps=fps), self.assertRaises(ValidationError):
                Settings(_env_file=None, gemini_video_fps=fps)
        for fps in (0, 0.5, 1, 1.5, 2):
            with self.subTest(fps=fps):
                self.assertEqual(Settings(_env_file=None, gemini_video_fps=fps).gemini_video_fps, float(fps))

    def test_unknown_resolution_is_refused(self) -> None:
        for value in ("ultra_high", "HIGH", "280"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Settings(_env_file=None, gemini_media_resolution=value)

    def test_guardrail_defaults_change_nothing(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual(settings.gemini_video_token_budget, 400_000)
        self.assertEqual(settings.gemini_max_output_tokens, 0)
        self.assertEqual(settings.gemini_thinking_level, "")

    def test_thinking_level_follows_the_sdk_levels(self) -> None:
        for value in ("minimal", "low", "medium", "high", "xhigh"):
            with self.subTest(value=value):
                self.assertEqual(Settings(_env_file=None, gemini_thinking_level=value).gemini_thinking_level, value)
        for value in ("LOW", "max", "THINKING_LEVEL_UNSPECIFIED"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Settings(_env_file=None, gemini_thinking_level=value)

    def test_negative_max_output_tokens_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, gemini_max_output_tokens=-1)


if __name__ == "__main__":
    unittest.main()


class MediaLimitSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual((settings.max_duration_seconds, settings.max_file_size_mb), (180, 200))
        self.assertEqual(
            (settings.signed_in_byok_max_duration_seconds, settings.signed_in_byok_max_file_size_mb), (600, 500)
        )
        self.assertEqual((settings.worker_job_timeout_seconds, settings.long_job_timeout_seconds), (600, 1800))

    def test_long_job_timeout_never_below_the_standard_one(self) -> None:
        settings = Settings(_env_file=None, worker_job_timeout_seconds=900, worker_long_job_timeout_seconds=300)
        self.assertEqual(settings.long_job_timeout_seconds, 900)
