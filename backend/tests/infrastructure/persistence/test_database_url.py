import unittest
from unittest import mock

from app.infrastructure.config import Settings
from app.infrastructure.persistence import database as database_module
from app.infrastructure.persistence.database import Database, normalize_database_url


class SslParameterTests(unittest.TestCase):
    def test_sslmode_becomes_asyncpgs_ssl_with_its_value(self) -> None:
        for mode in ("require", "verify-full", "disable", "prefer"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    normalize_database_url(f"postgresql://u:p@h:5432/postgres?sslmode={mode}"),
                    f"postgresql+asyncpg://u:p@h:5432/postgres?ssl={mode}",
                )

    def test_other_parameters_and_their_order_are_kept(self) -> None:
        self.assertEqual(
            normalize_database_url("postgres://u:p@h/db?application_name=vl&sslmode=require&connect_timeout=5"),
            "postgresql+asyncpg://u:p@h/db?application_name=vl&ssl=require&connect_timeout=5",
        )

    def test_an_explicit_ssl_wins(self) -> None:
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h/db?ssl=verify-full&sslmode=require"),
            "postgresql+asyncpg://u:p@h/db?ssl=verify-full",
        )

    def test_an_asyncpg_url_is_translated_too_and_plain_urls_are_untouched(self) -> None:
        self.assertEqual(
            normalize_database_url("postgresql+asyncpg://u:p@h/db?sslmode=require"),
            "postgresql+asyncpg://u:p@h/db?ssl=require",
        )
        self.assertEqual(normalize_database_url("postgresql://u:p@h/db"), "postgresql+asyncpg://u:p@h/db")
        self.assertEqual(normalize_database_url("sqlite:///x.db?sslmode=x"), "sqlite+aiosqlite:///x.db?sslmode=x")

    def test_sqlalchemy_hands_asyncpg_the_ssl_keyword(self) -> None:
        # What create_async_engine would call asyncpg.connect() with.
        from sqlalchemy.dialects.postgresql.asyncpg import dialect
        from sqlalchemy.engine import make_url

        url = make_url(normalize_database_url("postgresql://u:p@h:5432/db?sslmode=require"))
        _, kwargs = dialect().create_connect_args(url)
        self.assertEqual(kwargs["ssl"], "require")
        self.assertNotIn("sslmode", kwargs)


class PoolSettingsTests(unittest.TestCase):
    def test_pool_size_and_overflow_reach_the_engine(self) -> None:
        settings = Settings(
            _env_file=None, database_url="postgresql://u:p@h/db", database_pool_size=3, database_max_overflow=2
        )
        with mock.patch.object(database_module, "create_async_engine") as create:
            Database(settings).engine()
        kwargs = create.call_args.kwargs
        self.assertEqual((kwargs["pool_size"], kwargs["max_overflow"]), (3, 2))

    def test_defaults_are_sqlalchemys(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual((settings.database_pool_size, settings.database_max_overflow), (5, 10))


if __name__ == "__main__":
    unittest.main()
