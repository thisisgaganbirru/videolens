import json
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

        async def fake_eval(script, numkeys, key, value, ttl):
            # The write-unless-ended script: skip a missing or ended run.
            current = data.get(key)
            if current is None or json.loads(current)["status"] in ("complete", "failed"):
                return 0
            await client.set(key, value, ex=int(ttl))
            return 1

        client.set.side_effect = fake_set
        client.get.side_effect = fake_get
        client.eval.side_effect = fake_eval
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


class DeleteForOwnerTests(unittest.IsolatedAsyncioTestCase):
    """Account deletion (`DELETE /api/me`) removes one owner's runs only."""

    async def test_in_memory_removes_only_that_owners_runs(self) -> None:
        store = RunStore(Settings(_env_file=None))
        await store.create("a", "user:sub-1")
        await store.create("b", "user:sub-1")
        await store.create("c", "user:sub-2")

        self.assertEqual(await store.delete_for_owner("user:sub-1"), 2)
        self.assertEqual(await store.delete_for_owner("user:sub-1"), 0)

        self.assertIsNone(await store.get("a"))
        self.assertIsNotNone(await store.get("c"))

    async def test_redis_deletes_the_indexed_runs_and_the_index(self) -> None:
        store = RunStore(Settings(_env_file=None, redis_url="redis://test"))
        client = AsyncMock()
        client.zrange.return_value = ["a", "b"]
        client.delete.side_effect = [2, 1]
        store._redis = client  # type: ignore[assignment]

        self.assertEqual(await store.delete_for_owner("user:sub-1"), 2)

        client.zrange.assert_awaited_once_with("videolens:owner:user:sub-1:runs", 0, -1)
        self.assertEqual(
            [call.args for call in client.delete.await_args_list],
            [("videolens:run:a", "videolens:run:b"), ("videolens:owner:user:sub-1:runs",)],
        )

    async def test_redis_with_no_runs_still_drops_the_index(self) -> None:
        store = RunStore(Settings(_env_file=None, redis_url="redis://test"))
        client = AsyncMock()
        client.zrange.return_value = []
        store._redis = client  # type: ignore[assignment]

        self.assertEqual(await store.delete_for_owner("user:sub-1"), 0)
        client.delete.assert_awaited_once_with("videolens:owner:user:sub-1:runs")

    async def test_a_run_deleted_mid_flight_is_not_recreated(self) -> None:
        store = RunStore(Settings(_env_file=None))
        await store.create("busy", "user:sub-1")
        await store.delete_for_owner("user:sub-1")

        await store.set_error("busy", "late worker write")

        self.assertIsNone(await store.get("busy"))



_ANALYSIS = VideoAnalysis(title="T", summary="S", transcript="", screen_text="", markdown="")


class EndedRunsAreFinalTests(unittest.IsolatedAsyncioTestCase):
    """2026-11-13: whichever of the worker's result and the stale-run
    sweep's failure lands first is the run's outcome."""

    async def test_in_memory_a_failed_run_is_not_resurrected_by_a_late_result(self) -> None:
        store = RunStore(Settings(_env_file=None))
        await store.create("run-1", "client:o")
        self.assertTrue(await store.set_error("run-1", "stopped responding"))

        self.assertFalse(await store.set_result("run-1", _ANALYSIS))
        await store.set_stage("run-1", "analyzing")
        await store.set_status("run-1", RunStatus.PROCESSING)

        saved = await store.get("run-1")
        assert saved is not None
        self.assertEqual(saved.status, RunStatus.FAILED)
        self.assertEqual(saved.error, "stopped responding")
        self.assertIsNone(saved.result)
        self.assertIsNone(saved.stage)

    async def test_in_memory_a_completed_run_is_not_failed_by_a_late_sweep(self) -> None:
        store = RunStore(Settings(_env_file=None))
        await store.create("run-1", "client:o")
        self.assertTrue(await store.set_result("run-1", _ANALYSIS))

        self.assertFalse(await store.set_error("run-1", "stopped responding"))

        saved = await store.get("run-1")
        assert saved is not None
        self.assertEqual(saved.status, RunStatus.COMPLETE)
        self.assertIsNone(saved.error)

    async def test_writes_to_a_missing_run_report_false(self) -> None:
        store = RunStore(Settings(_env_file=None))
        self.assertFalse(await store.set_result("gone", _ANALYSIS))
        self.assertFalse(await store.set_error("gone", "x"))

    def _redis_store(self) -> tuple[RunStore, AsyncMock, dict[str, str]]:
        store = RunStore(Settings(_env_file=None, redis_url="redis://test", run_ttl_seconds=3600))
        data: dict[str, str] = {}
        client = AsyncMock()

        async def fake_set(key, value, ex=None):
            data[key] = value

        async def fake_get(key):
            return data.get(key)

        async def fake_eval(script, numkeys, key, value, ttl):
            current = data.get(key)
            if current is None or json.loads(current)["status"] in ("complete", "failed"):
                return 0
            data[key] = value
            return 1

        client.set.side_effect = fake_set
        client.get.side_effect = fake_get
        client.eval.side_effect = fake_eval
        store._redis = client  # type: ignore[assignment]
        return store, client, data

    async def test_redis_updates_go_through_the_guarded_script(self) -> None:
        store, client, _ = self._redis_store()
        await store.create("run-1", "client:o")
        client.set.reset_mock()

        await store.set_stage("run-1", "downloading")

        client.set.assert_not_awaited()
        script, numkeys, key, _payload, ttl = client.eval.await_args.args
        self.assertIn("cjson.decode", script)
        self.assertEqual((numkeys, key, ttl), (1, "videolens:run:run-1", 3600))

    async def test_redis_result_after_the_sweep_failed_the_run_is_refused(self) -> None:
        store, client, data = self._redis_store()
        await store.create("run-1", "client:o")
        await store.set_error("run-1", "stopped responding")
        client.expire.reset_mock()

        self.assertFalse(await store.set_result("run-1", _ANALYSIS))

        self.assertEqual(json.loads(data["videolens:run:run-1"])["status"], "failed")
        client.expire.assert_not_awaited()

    async def test_redis_race_the_record_ended_between_read_and_write(self) -> None:
        # The worker read `processing`, then the sweep failed the run before
        # the worker's write: the script sees `failed` and refuses.
        store, client, data = self._redis_store()
        await store.create("run-1", "client:o")
        real_get = client.get.side_effect

        async def get_then_sweep(key):
            payload = await real_get(key)
            doc = json.loads(data[key])
            doc["status"] = "failed"
            data[key] = json.dumps(doc)
            return payload

        client.get.side_effect = get_then_sweep

        self.assertFalse(await store.set_result("run-1", _ANALYSIS))
        self.assertEqual(json.loads(data["videolens:run:run-1"])["status"], "failed")


if __name__ == "__main__":
    unittest.main()
