import unittest
from datetime import timedelta
from unittest.mock import AsyncMock

from app.domain.entities import MediaVisuals, Run, RunStatus, VideoAnalysis
from app.infrastructure.config import Settings
from app.infrastructure.persistence.run_repository import RunStore


class RunStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.store = RunStore(Settings())

    async def test_run_lifecycle_keeps_owner(self) -> None:
        run = await self.store.create("run-1", "client:test-client-1234")
        self.assertEqual(run.status, RunStatus.QUEUED)
        self.assertEqual(run.owner_id, "client:test-client-1234")

        await self.store.set_stage(run.run_id, "analyzing")
        await self.store.set_result(
            run.run_id,
            VideoAnalysis(
                title="Test",
                summary="Summary",
                transcript="Transcript",
                screen_text="",
                markdown="# Test",
            ),
        )

        saved = await self.store.get(run.run_id)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.owner_id, run.owner_id)
        self.assertEqual(saved.status, RunStatus.COMPLETE)
        self.assertEqual(saved.stage, "analyzing")

    async def test_list_for_owner_returns_only_that_owners_runs_newest_first(self) -> None:
        await self.store.create("run-a", "client:owner-1")
        await self.store.create("run-b", "client:owner-2")
        await self.store.create("run-c", "client:owner-1")

        history = await self.store.list_for_owner("client:owner-1")

        self.assertEqual([run.run_id for run in history], ["run-c", "run-a"])

    async def test_list_for_owner_respects_limit(self) -> None:
        for i in range(5):
            await self.store.create(f"run-{i}", "client:owner-1")

        history = await self.store.list_for_owner("client:owner-1", limit=2)

        self.assertEqual(len(history), 2)

    async def test_create_records_media_facts_and_set_duration_updates_them(self) -> None:
        run = await self.store.create(
            "run-f", "client:owner-1", source_kind="file", platform="audio_file", duration_seconds=3.5
        )
        self.assertEqual(run.source_kind, "file")
        self.assertEqual(run.platform, "audio_file")

        await self.store.set_duration("run-f", 4.0)

        saved = await self.store.get("run-f")
        assert saved is not None
        self.assertEqual(saved.duration_seconds, 4.0)
        self.assertEqual(saved.platform, "audio_file")

    async def test_set_duration_on_a_missing_run_is_a_no_op(self) -> None:
        await self.store.set_duration("nope", 1.0)
        self.assertIsNone(await self.store.get("nope"))


class LegacyRunPayloadTests(unittest.TestCase):
    def test_a_run_stored_before_the_media_fields_existed_still_deserializes(self) -> None:
        # Exactly what Redis holds for a run written by the previous release.
        payload = (
            '{"run_id":"old","owner_id":"client:o","status":"complete",'
            '"created_at":"2026-10-01T00:00:00Z","updated_at":"2026-10-01T00:01:00Z",'
            '"stage":null,"result":null,"error":null,"source_metadata":null,'
            '"completeness":"full"}'
        )
        run = Run.model_validate_json(payload)
        self.assertIsNone(run.source_kind)
        self.assertIsNone(run.platform)
        self.assertIsNone(run.duration_seconds)


class RetentionTests(unittest.IsolatedAsyncioTestCase):
    """Phase 5a: the browser keeps History, the server keeps a run ~1 hour."""

    def test_default_ttl_is_one_hour(self) -> None:
        self.assertEqual(Settings(_env_file=None).run_ttl_seconds, 3600)

    def _redis_store(self) -> tuple[RunStore, AsyncMock]:
        store = RunStore(Settings(_env_file=None, redis_url="redis://test", run_ttl_seconds=3600))
        data: dict[str, str] = {}
        client = AsyncMock()

        async def fake_set(key, value, ex=None):
            data[key] = value

        async def fake_get(key):
            return data.get(key)

        client.set.side_effect = fake_set
        client.get.side_effect = fake_get
        store._redis = client  # type: ignore[assignment]
        return store, client

    async def test_completion_rearms_the_run_ttl_and_the_owner_index(self) -> None:
        store, client = self._redis_store()
        await store.create("run-1", "client:o")
        client.set.reset_mock()
        client.expire.reset_mock()

        await store.set_result(
            "run-1",
            VideoAnalysis(title="T", summary="S", transcript="", screen_text="", markdown=""),
        )

        self.assertEqual(client.set.await_args.args[0], "videolens:run:run-1")
        self.assertEqual(client.set.await_args.kwargs["ex"], 3600)
        client.expire.assert_awaited_once_with("videolens:owner:client:o:runs", 3600)

    async def test_failure_rearms_the_run_ttl_and_the_owner_index(self) -> None:
        store, client = self._redis_store()
        await store.create("run-1", "client:o")
        client.expire.reset_mock()

        await store.set_error("run-1", "nope")

        self.assertEqual(client.set.await_args.kwargs["ex"], 3600)
        client.expire.assert_awaited_once_with("videolens:owner:client:o:runs", 3600)

    async def test_in_memory_runs_expire_after_the_ttl(self) -> None:
        store = RunStore(Settings(_env_file=None, run_ttl_seconds=3600))
        await store.create("old", "client:o")
        old = await store.get("old")
        assert old is not None
        old.updated_at = old.updated_at - timedelta(seconds=3601)

        await store.create("new", "client:o")  # any write prunes

        self.assertIsNone(await store.get("old"))
        self.assertIsNotNone(await store.get("new"))

    async def test_a_late_finish_gets_a_full_window_in_memory(self) -> None:
        store = RunStore(Settings(_env_file=None, run_ttl_seconds=3600))
        await store.create("slow", "client:o")
        run = await store.get("slow")
        assert run is not None
        run.updated_at = run.updated_at - timedelta(seconds=3500)

        await store.set_error("slow", "late")  # re-stamps updated_at
        run = await store.get("slow")
        assert run is not None
        run.created_at = run.created_at - timedelta(seconds=3500)
        await store.create("other", "client:o")

        self.assertIsNotNone(await store.get("slow"))


class VisualsTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_visuals_round_trips_and_keeps_none_fields(self) -> None:
        store = RunStore(Settings(_env_file=None))
        await store.create("run-v", "client:o")

        await store.set_visuals(
            "run-v", MediaVisuals(thumbnail="data:image/jpeg;base64,AA", width=720, height=1280)
        )
        await store.set_visuals("run-v", MediaVisuals())  # nothing new: nothing lost

        saved = await store.get("run-v")
        assert saved is not None
        self.assertEqual(saved.thumbnail, "data:image/jpeg;base64,AA")
        self.assertEqual((saved.width, saved.height), (720, 1280))

    async def test_set_visuals_on_a_missing_run_is_a_no_op(self) -> None:
        store = RunStore(Settings(_env_file=None))
        await store.set_visuals("nope", MediaVisuals(width=1, height=1))
        self.assertIsNone(await store.get("nope"))

    def test_a_legacy_payload_has_no_visuals(self) -> None:
        run = Run.model_validate_json(
            '{"run_id":"old","owner_id":"client:o","status":"complete",'
            '"created_at":"2026-10-01T00:00:00Z","updated_at":"2026-10-01T00:01:00Z",'
            '"completeness":"full","source_kind":"link","duration_seconds":12.0}'
        )
        self.assertIsNone(run.thumbnail)
        self.assertIsNone(run.width)
        self.assertIsNone(run.height)


if __name__ == "__main__":
    unittest.main()
