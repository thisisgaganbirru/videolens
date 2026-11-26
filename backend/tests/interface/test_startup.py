import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.application.check_schema import CheckSchemaUseCase
from app.domain.errors import SchemaOutOfDateError
from app.domain.schema_revision import SchemaReading
from app.infrastructure.config import Settings
from app.interface.startup import API, WORKER, mode_fingerprint, validate_startup

DISTRIBUTED = dict(redis_url="redis://r:6379/0", allowed_origins="https://app.test")
STRIPE = dict(
    stripe_secret_key="sk_test_secret_value",
    stripe_webhook_secret="whsec_secret_value",
    stripe_price_monthly="price_m",
    stripe_price_extra_run="price_x",
)
POSTGRES = "postgresql://videolens_api.ref:hunter2-password@pooler.test:5432/postgres"


class FixedReader:
    def __init__(self, reading: SchemaReading) -> None:
        self.reading = reading

    async def read(self) -> SchemaReading:
        return self.reading


def fake_container(*, reader=None, enforce=True, dialect="", **settings) -> SimpleNamespace:
    """Only what validate_startup and the mode line touch."""
    return SimpleNamespace(
        settings=Settings(_env_file=None, **settings),
        media=Mock(),
        device_tokens=Mock(),
        object_store=SimpleNamespace(enabled=True),
        run_repository=SimpleNamespace(ping=AsyncMock(return_value=True)),
        check_schema_use_case=CheckSchemaUseCase(reader=reader, enforce=enforce),
        database=SimpleNamespace(dialect=dialect),
        billing_gateway=SimpleNamespace(enabled=False),
        jwt_verifier=SimpleNamespace(configured=False),
    )


class SharedValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_refuses_billing_without_a_database(self) -> None:
        container = fake_container(**DISTRIBUTED, **STRIPE)
        with self.assertRaisesRegex(RuntimeError, "without DATABASE_URL"):
            await validate_startup(container, WORKER)

    async def test_worker_refuses_sqlite_when_distributed(self) -> None:
        container = fake_container(**DISTRIBUTED, database_url="sqlite+aiosqlite:///x.db")
        with self.assertRaisesRegex(RuntimeError, "SQLite"):
            await validate_startup(container, WORKER)

    async def test_worker_requires_redis_and_object_storage(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Worker requires Redis"):
            await validate_startup(fake_container(), WORKER)

    async def test_cors_and_device_tokens_are_the_apis_alone(self) -> None:
        worker_side = fake_container(**{**DISTRIBUTED, "allowed_origins": "*"})
        await validate_startup(worker_side, WORKER)
        worker_side.device_tokens.validate_configuration.assert_not_called()

        api_side = fake_container(**{**DISTRIBUTED, "allowed_origins": "*"})
        with self.assertRaisesRegex(RuntimeError, "ALLOWED_ORIGINS"):
            await validate_startup(api_side, API)
        api_side.device_tokens.validate_configuration.assert_called_once()

    async def test_both_roles_run_the_schema_check(self) -> None:
        for role in (API, WORKER):
            with self.subTest(role=role):
                container = fake_container(
                    reader=FixedReader(SchemaReading(revisions=("0006_saved_history",))),
                    dialect="postgresql",
                    database_url=POSTGRES,
                    **DISTRIBUTED,
                )
                with self.assertRaisesRegex(SchemaOutOfDateError, "0006_saved_history"):
                    await validate_startup(container, role)

    async def test_a_consistent_worker_starts(self) -> None:
        container = fake_container(
            reader=FixedReader(SchemaReading(revisions=("0010_complimentary_plus",))),
            dialect="postgresql",
            database_url=POSTGRES,
            **DISTRIBUTED,
            **STRIPE,
        )
        with self.assertLogs("videolens", level="INFO") as logs:
            await validate_startup(container, WORKER)
        container.run_repository.ping.assert_awaited_once()
        mode = [line for line in logs.output if "Startup mode" in line]
        self.assertEqual(len(mode), 1)
        self.assertIn('"role": "worker"', mode[0])
        self.assertIn('"schema": "ok"', mode[0])
        self.assertIn('"mode": "distributed"', mode[0])


class ModeFingerprintTests(unittest.TestCase):
    def test_switches_only_never_values(self) -> None:
        container = fake_container(dialect="postgresql", database_url=POSTGRES, **DISTRIBUTED, **STRIPE)
        fingerprint = mode_fingerprint(container, WORKER)
        text = repr(fingerprint)
        for secret in ("hunter2", "sk_test", "whsec", "pooler.test", "redis://"):
            self.assertNotIn(secret, text)
        self.assertEqual(fingerprint["database"], "postgresql")
        self.assertEqual(fingerprint["schema"], "unchecked")

    def test_no_database_is_off(self) -> None:
        self.assertEqual(mode_fingerprint(fake_container(), API)["database"], "off")


if __name__ == "__main__":
    unittest.main()
