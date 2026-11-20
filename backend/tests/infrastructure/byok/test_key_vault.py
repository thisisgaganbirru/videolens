"""The BYOK vault hands a stored key out at most once, even to two takes in
flight at the same time (docs/backend/byok.md)."""

import asyncio
import unittest

from app.infrastructure.byok.key_vault import ByokKeyStore
from app.infrastructure.config import Settings


class _FakeRedis:
    """What the vault uses: `set`, and `eval` of its take script. Every await
    yields first, so two takes interleave the way two workers on one Redis
    would; the script runs as one step, as Redis runs a script."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.calls: list[str] = []

    async def set(self, name: str, value: str, ex: int | None = None) -> None:
        await asyncio.sleep(0)
        self.data[name] = value

    async def get(self, name: str) -> str | None:
        await asyncio.sleep(0)
        self.calls.append("get")
        return self.data.get(name)

    async def delete(self, name: str) -> int:
        await asyncio.sleep(0)
        self.calls.append("delete")
        return 1 if self.data.pop(name, None) is not None else 0

    async def eval(self, script: str, numkeys: int, *keys_and_args):
        await asyncio.sleep(0)
        self.calls.append("eval")
        assert numkeys == 1 and "GET" in script and "DEL" in script
        return self.data.pop(keys_and_args[0], None)  # atomic on the server

    async def aclose(self) -> None:
        return None


class ByokKeyStoreTests(unittest.IsolatedAsyncioTestCase):
    def test_the_take_script_needs_no_newer_redis_command(self) -> None:
        # Plain GET and DEL only (any Redis with scripting, 2.6+): never GETDEL.
        from app.infrastructure.byok import key_vault

        self.assertNotIn("GETDEL", key_vault._TAKE.upper())
        self.assertIn("redis.call('GET', KEYS[1])", key_vault._TAKE)
        self.assertIn("redis.call('DEL', KEYS[1])", key_vault._TAKE)

    def _distributed(self) -> tuple[ByokKeyStore, _FakeRedis]:
        store = ByokKeyStore(Settings(_env_file=None, redis_url="redis://fake:6379/0", gemini_api_key="ci-test-key"))
        fake = _FakeRedis()
        store._redis = fake
        return store, fake

    async def test_two_concurrent_takes_yield_the_key_once(self) -> None:
        store, fake = self._distributed()
        await store.store("run-1", "AIza-secret")
        taken = await asyncio.gather(store.take("run-1"), store.take("run-1"))
        self.assertEqual(sorted(taken, key=str), ["AIza-secret", None])
        self.assertEqual(fake.calls, ["eval", "eval"])
        self.assertEqual(fake.data, {})

    async def test_a_missing_key_is_none(self) -> None:
        store, _ = self._distributed()
        self.assertIsNone(await store.take("run-unknown"))

    async def test_in_process_mode_is_single_use_too(self) -> None:
        store = ByokKeyStore(Settings(_env_file=None, redis_url="", gemini_api_key="ci-test-key"))
        await store.store("run-1", "AIza-secret")
        self.assertEqual(await asyncio.gather(store.take("run-1"), store.take("run-1")), ["AIza-secret", None])


if __name__ == "__main__":
    unittest.main()
