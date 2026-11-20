import os
import ssl
import tempfile
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
            normalize_database_url("postgres://u:p@h/db?target_session_attrs=primary&sslmode=require&command_timeout=5"),
            "postgresql+asyncpg://u:p@h/db?target_session_attrs=primary&ssl=require&command_timeout=5",
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


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, database_url=url)


def _write_ca(directory: str) -> str:
    """A self-signed CA certificate in PEM, enough for `load_verify_locations`."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = os.path.join(directory, "ca.crt")
    with open(path, "wb") as handle:
        handle.write(cert.public_bytes(serialization.Encoding.PEM))
    return path


class UnsupportedParameterTests(unittest.TestCase):
    """A parameter asyncpg cannot take used to reach `connect()` and fail
    every connection with a TypeError at the first query; it is now refused
    when the `Database` is built, so the process does not start."""

    def test_libpq_only_parameters_are_refused_by_name(self) -> None:
        url = "postgresql://u:secret@h/db?options=-c%20search_path%3Dx&sslmode=require&application_name=vl"
        with self.assertRaises(ValueError) as caught:
            Database(_settings(url))
        message = str(caught.exception)
        self.assertIn("application_name, options", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("search_path", message)

    def test_a_client_certificate_is_refused_not_dropped(self) -> None:
        with self.assertRaises(ValueError) as caught:
            Database(_settings("postgresql://u:p@h/db?sslmode=verify-full&sslcert=/c.crt&sslkey=/c.key"))
        self.assertIn("sslcert, sslkey", str(caught.exception))

    def test_an_empty_sslmode_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Database(_settings("postgresql://u:p@h/db?sslmode"))

    def test_sslrootcert_needs_a_verifying_mode(self) -> None:
        for mode in ("require", "prefer"):
            with self.subTest(mode=mode), self.assertRaises(ValueError) as caught:
                Database(_settings(f"postgresql://u:p@h/db?sslmode={mode}&sslrootcert=/x.crt"))
            self.assertIn("verify-full", str(caught.exception))

    def test_an_unreadable_root_certificate_is_refused_at_startup(self) -> None:
        with self.assertRaises(ValueError) as caught:
            Database(_settings("postgresql://u:p@h/db?sslmode=verify-full&sslrootcert=/no/such/ca.crt"))
        self.assertIn("sslrootcert could not be loaded", str(caught.exception))

    def test_the_accepted_forms_still_build(self) -> None:
        for url in ("", "sqlite:///x.db", "postgresql://u:p@h/db", "postgresql://u:p@h/db?sslmode=require&command_timeout=5"):
            with self.subTest(url=url):
                Database(_settings(url))


class RootCertificateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ca = _write_ca(directory.name)

    def _engine_kwargs(self, mode: str) -> tuple[str, dict]:
        url = f"postgresql://u:p@h:5432/db?sslmode={mode}&sslrootcert={self.ca}&command_timeout=5"
        with mock.patch.object(database_module, "create_async_engine") as create:
            Database(_settings(url)).engine()
        return create.call_args.args[0], create.call_args.kwargs["connect_args"]

    def test_verify_full_becomes_a_context_trusting_that_ca_and_checking_the_host(self) -> None:
        url, connect_args = self._engine_kwargs("verify-full")
        context = connect_args["ssl"]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(len(context.get_ca_certs()), 1)
        # Neither parameter is passed on to asyncpg; the others are kept.
        self.assertEqual(url, "postgresql+asyncpg://u:p@h:5432/db?command_timeout=5")

    def test_verify_ca_verifies_the_chain_but_not_the_host(self) -> None:
        _, connect_args = self._engine_kwargs("verify-ca")
        context = connect_args["ssl"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(context.check_hostname)

    def test_what_asyncpg_receives(self) -> None:
        from sqlalchemy.dialects.postgresql.asyncpg import dialect
        from sqlalchemy.engine import make_url

        url, connect_args = self._engine_kwargs("verify-full")
        _, kwargs = dialect().create_connect_args(make_url(url))
        self.assertNotIn("sslrootcert", kwargs)
        self.assertNotIn("ssl", kwargs)  # the context comes in connect_args
        self.assertIn("ssl", connect_args)

    def test_without_sslrootcert_nothing_extra_is_passed(self) -> None:
        with mock.patch.object(database_module, "create_async_engine") as create:
            Database(_settings("postgresql://u:p@h/db?sslmode=require")).engine()
        self.assertNotIn("ssl", create.call_args.kwargs["connect_args"])
        self.assertTrue(create.call_args.args[0].endswith("?ssl=require"))


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
