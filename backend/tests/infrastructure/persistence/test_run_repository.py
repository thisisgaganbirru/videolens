import unittest

from app.domain.entities import Run, RunStatus, VideoAnalysis
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


if __name__ == "__main__":
    unittest.main()
