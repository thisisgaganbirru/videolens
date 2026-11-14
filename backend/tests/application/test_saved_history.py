"""Saved history (docs/backend/saved-history.md): a paid account's results
saved once on success, never for free or anonymous callers; the API side
scoped to the caller's own account; the post-cancel window, its expiry and
a resubscribe; the deletion hold, restore and the cleanup job.

Billing is the real `BillingPlans` over the in-memory stores and the fake
Stripe gateway (as in test_billing); saved runs are the in-memory adapter,
which shares its behaviour suite with the SQL one."""

import unittest
from datetime import datetime, timedelta, timezone

from app.application.cleanup import AccountCleanupUseCase
from app.application.handle_billing_webhook import HandleBillingWebhookUseCase
from app.application.process_run import ProcessRunUseCase
from app.application.restore_account import RestoreAccountUseCase
from app.application.saved_history import SavedHistory, SavedHistoryQueries, encode_cursor
from app.domain.entities import (
    AnalysisCompleteness,
    AuthMethod,
    BillingWebhookEvent,
    MediaVisuals,
    Principal,
    RunStatus,
    SavedRunCursor,
    VideoAnalysis,
)
from app.domain.errors import InvalidCursorError, SavedRunNotFoundError
from app.infrastructure.persistence.account_deleter import InMemoryAccountDeleter
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.saved_run_repository import InMemorySavedRuns

from .fakes import FakeRunRepository
from .test_billing import ACCOUNT, ANALYSIS, CUSTOMER, SETTINGS, URL, _Billing, _Pipeline, _snapshot

OTHER = "acct-2"
POSTER = "data:image/jpeg;base64," + "A" * 4000


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _person(account_id: str | None = ACCOUNT) -> Principal:
    return Principal(subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id=account_id)


class _History:
    """Billing, a run store and saved history over one clock."""

    def __init__(self, *, enabled: bool = True, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.clock = _Clock()
        self.billing = _Billing(enabled=enabled, clock=self.clock)
        self.runs = FakeRunRepository()
        self.saved = InMemorySavedRuns(SETTINGS)
        self.history = SavedHistory(
            runs=self.runs,
            saved_runs=self.saved,
            plans=self.billing.plans,
            grace_days=30,
            max_bytes=max_bytes,
            clock=self.clock,
        )
        self.queries = SavedHistoryQueries(history=self.history)

    async def subscribe(self, status: str = "active", account_id: str = ACCOUNT, **kwargs) -> None:
        await self.billing.accounts.link_customer(account_id, f"cus_{account_id}")
        snapshot = _snapshot(status, customer=f"cus_{account_id}", **kwargs)
        await self.billing.accounts.apply_subscription(account_id, snapshot)

    async def finished_run(
        self,
        run_id: str,
        account_id: str | None = ACCOUNT,
        result: VideoAnalysis = ANALYSIS,
        thumbnail: str | None = None,
    ) -> str:
        await self.runs.create(run_id, "user:sub-1", source_kind="link", platform="direct", account_id=account_id)
        if thumbnail is not None:
            await self.runs.set_visuals(run_id, MediaVisuals(thumbnail=thumbnail, width=1280, height=720))
        await self.runs.set_result(run_id, result, AnalysisCompleteness.FULL)
        return run_id


class SavingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.h = _History()

    async def test_a_paid_success_is_saved_once(self) -> None:
        await self.h.subscribe()
        run_id = await self.h.finished_run("run-1")

        self.assertTrue(await self.h.history.save_completed(run_id, source_url=URL))
        self.assertFalse(await self.h.history.save_completed(run_id, source_url=URL))  # idempotent

        self.assertEqual(await self.h.saved.count(ACCOUNT), 1)
        saved = await self.h.queries.get(_person(), run_id)
        self.assertEqual((saved.title, saved.completeness), ("T", "full"))
        self.assertEqual(saved.result["transcript"], "Tx")
        self.assertEqual(saved.result["markdown"], "# T")
        self.assertEqual(saved.source.source_kind, "link")
        self.assertEqual(saved.source.source_url, URL)

    async def test_free_anonymous_and_billing_off_are_never_saved(self) -> None:
        free = await self.h.finished_run("free-run")
        anonymous = await self.h.finished_run("anon-run", account_id=None)
        self.assertFalse(await self.h.history.save_completed(free))
        self.assertFalse(await self.h.history.save_completed(anonymous))
        for status in ("canceled", "past_due", "unpaid", "incomplete"):
            with self.subTest(status=status):
                h = _History()
                await h.subscribe(status)
                self.assertFalse(await h.history.save_completed(await h.finished_run("r")))
        off = _History(enabled=False)
        await off.subscribe()
        self.assertFalse(await off.history.save_completed(await off.finished_run("r")))
        self.assertEqual(await self.h.saved.count(ACCOUNT), 0)

    async def test_only_a_complete_run_is_saved(self) -> None:
        await self.h.subscribe()
        await self.h.runs.create("queued", "user:sub-1", account_id=ACCOUNT)
        self.assertFalse(await self.h.history.save_completed("queued"))
        self.assertFalse(await self.h.history.save_completed("missing"))

    async def test_a_file_run_keeps_no_link(self) -> None:
        await self.h.subscribe()
        await self.h.runs.create("file-run", "user:sub-1", source_kind="file", account_id=ACCOUNT)
        await self.h.runs.set_result("file-run", ANALYSIS)
        await self.h.history.save_completed("file-run", source_url=URL)
        saved = await self.h.queries.get(_person(), "file-run")
        self.assertIsNone(saved.source.source_url)

    async def test_a_save_failure_is_logged_and_swallowed(self) -> None:
        await self.h.subscribe()

        async def broken(run) -> bool:
            raise RuntimeError("db down")

        self.h.saved.save = broken  # type: ignore[method-assign]
        with self.assertLogs("videolens", "ERROR"):
            self.assertFalse(await self.h.history.save_completed(await self.h.finished_run("run-1")))

    async def test_an_oversized_result_drops_its_segments_then_is_skipped(self) -> None:
        big = VideoAnalysis.model_validate(
            {
                **ANALYSIS.model_dump(),
                "transcript_segments": [
                    {"start_seconds": i, "end_seconds": i + 1, "text": "x" * 200} for i in range(50)
                ],
            }
        )
        with_segments = len(big.model_dump_json())
        trimmed = _History(max_bytes=with_segments - 100)
        await trimmed.subscribe()
        with self.assertLogs("videolens", "WARNING"):
            self.assertTrue(await trimmed.history.save_completed(await trimmed.finished_run("r", result=big)))
        self.assertNotIn("transcript_segments", (await trimmed.queries.get(_person(), "r")).result)

        tiny = _History(max_bytes=10)
        await tiny.subscribe()
        with self.assertLogs("videolens", "ERROR"):
            self.assertFalse(await tiny.history.save_completed(await tiny.finished_run("r", result=big)))
        self.assertEqual(await tiny.saved.count(ACCOUNT), 0)


    async def test_the_poster_is_saved_as_the_live_run_exposes_it(self) -> None:
        await self.h.subscribe()
        await self.h.history.save_completed(await self.h.finished_run("with", thumbnail=POSTER))
        await self.h.history.save_completed(await self.h.finished_run("without"))

        self.assertEqual((await self.h.queries.get(_person(), "with")).thumbnail, POSTER)
        self.assertIsNone((await self.h.queries.get(_person(), "without")).thumbnail)
        listed = {item.run_id: item.thumbnail for item in (await self.h.queries.list(_person())).items}
        self.assertEqual(listed, {"with": POSTER, "without": None})

    async def test_the_size_guard_drops_segments_before_the_poster(self) -> None:
        big = VideoAnalysis.model_validate(
            {
                **ANALYSIS.model_dump(),
                "transcript_segments": [
                    {"start_seconds": i, "end_seconds": i + 1, "text": "x" * 200} for i in range(50)
                ],
            }
        )
        full = len(big.model_dump_json()) + len(POSTER)
        no_segments = len(ANALYSIS.model_dump_json()) + len(POSTER)

        # Room for the poster once the segments are gone: poster kept.
        keeps = _History(max_bytes=no_segments + 50)
        self.assertLess(keeps.history.max_bytes, full)
        await keeps.subscribe()
        with self.assertLogs("videolens", "WARNING") as logs:
            self.assertTrue(await keeps.history.save_completed(await keeps.finished_run("r", result=big, thumbnail=POSTER)))
        saved = await keeps.queries.get(_person(), "r")
        self.assertNotIn("transcript_segments", saved.result)
        self.assertEqual(saved.thumbnail, POSTER)
        self.assertIn("segment lists", logs.output[0])
        self.assertNotIn("poster", logs.output[0])

        # Still over without segments: the poster goes next, the text stays.
        drops = _History(max_bytes=no_segments - 100)
        await drops.subscribe()
        with self.assertLogs("videolens", "WARNING") as logs:
            self.assertTrue(await drops.history.save_completed(await drops.finished_run("r", result=big, thumbnail=POSTER)))
        saved = await drops.queries.get(_person(), "r")
        self.assertNotIn("transcript_segments", saved.result)
        self.assertIsNone(saved.thumbnail)
        self.assertEqual(saved.result["transcript"], "Tx")
        self.assertIn("segment lists and poster", logs.output[0])

        # Still over without both: not saved.
        tiny = _History(max_bytes=10)
        await tiny.subscribe()
        with self.assertLogs("videolens", "ERROR"):
            self.assertFalse(await tiny.history.save_completed(await tiny.finished_run("r", result=big, thumbnail=POSTER)))
        self.assertEqual(await tiny.saved.count(ACCOUNT), 0)


class PipelineSavingTests(unittest.IsolatedAsyncioTestCase):
    """The seam: the worker saves right after the result is stored and the
    extra run billed; a save failure never fails or un-bills the run."""

    async def asyncSetUp(self) -> None:
        self.billing = _Billing()
        await self.billing.subscribe()
        self.pipeline = _Pipeline(self.billing)
        self.saved = InMemorySavedRuns(SETTINGS)
        history = SavedHistory(runs=self.pipeline.runs, saved_runs=self.saved, plans=self.billing.plans)
        p = self.pipeline
        p.process = ProcessRunUseCase(
            runs=p.runs,
            media=p.media,
            storage=p.process._storage,
            analysis=p.analysis,
            free_runs=p.free_runs,
            account_free_runs=p.account_runs,
            entitlements=p.entitlements,
            extra_runs=self.billing.extra_runs,
            history=history,
        )

    async def test_a_paid_run_is_saved_by_the_worker(self) -> None:
        run_id = await self.pipeline.run()
        self.assertEqual((await self.pipeline.runs.get(run_id)).status, RunStatus.COMPLETE)
        page = await self.saved.list_page(ACCOUNT, limit=10)
        self.assertEqual([item.run_id for item in page.items], [run_id])

    async def test_a_save_failure_leaves_the_run_complete(self) -> None:
        async def broken(run) -> bool:
            raise RuntimeError("db down")

        self.saved.save = broken  # type: ignore[method-assign]
        with self.assertLogs("videolens", "ERROR"):
            run_id = await self.pipeline.run()
        self.assertEqual((await self.pipeline.runs.get(run_id)).status, RunStatus.COMPLETE)


class QueryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.h = _History()
        await self.h.subscribe()
        await self.h.subscribe(account_id=OTHER)
        for index in range(5):
            run_id = await self.h.finished_run(f"mine-{index}")
            self.h.runs.runs[run_id].created_at = self.h.clock.now - timedelta(minutes=index)
            await self.h.history.save_completed(run_id)
        await self.h.history.save_completed(await self.h.finished_run("theirs", account_id=OTHER))

    async def test_pages_are_newest_first_and_walk_with_the_cursor(self) -> None:
        seen: list[str] = []
        cursor = None
        while True:
            page = await self.h.queries.list(_person(), limit=2, cursor=cursor)
            seen.extend(item.run_id for item in page.items)
            cursor = encode_cursor(page.next_cursor)
            if cursor is None:
                break
        self.assertEqual(seen, [f"mine-{i}" for i in range(5)])

    async def test_a_bad_cursor_is_an_error(self) -> None:
        with self.assertRaises(InvalidCursorError):
            await self.h.queries.list(_person(), cursor="!!not-a-cursor!!")

    async def test_accounts_never_see_or_delete_each_other(self) -> None:
        theirs = _person(OTHER)
        self.assertEqual([i.run_id for i in (await self.h.queries.list(theirs)).items], ["theirs"])
        with self.assertRaises(SavedRunNotFoundError):
            await self.h.queries.get(theirs, "mine-0")
        with self.assertRaises(SavedRunNotFoundError):
            await self.h.queries.delete(theirs, "mine-0")
        self.assertEqual(await self.h.queries.delete_all(theirs), 1)
        self.assertEqual(await self.h.saved.count(ACCOUNT), 5)

    async def test_delete_one_then_all(self) -> None:
        await self.h.queries.delete(_person(), "mine-0")
        with self.assertRaises(SavedRunNotFoundError):
            await self.h.queries.get(_person(), "mine-0")
        with self.assertRaises(SavedRunNotFoundError):
            await self.h.queries.delete(_person(), "mine-0")
        self.assertEqual(await self.h.queries.delete_all(_person()), 4)
        self.assertEqual((await self.h.queries.list(_person())).items, [])

    async def test_a_free_account_gets_an_empty_list_and_saving_false(self) -> None:
        stranger = _person("acct-free")
        self.assertEqual((await self.h.queries.list(stranger)).items, [])
        status = await self.h.queries.status(stranger)
        self.assertEqual((status.saving, status.expires_at), (False, None))
        self.assertTrue((await self.h.queries.status(_person())).saving)

    async def test_no_account_reads_nothing(self) -> None:
        anonymous = _person(None)
        self.assertEqual((await self.h.queries.list(anonymous)).items, [])
        self.assertEqual(await self.h.queries.delete_all(anonymous), 0)


class WindowTests(unittest.IsolatedAsyncioTestCase):
    """The post-cancel window: armed when the plan ends, cleared by a
    resubscribe, purged once it passes."""

    async def asyncSetUp(self) -> None:
        self.h = _History()
        await self.h.subscribe()
        await self.h.history.save_completed(await self.h.finished_run("run-1"))
        self.webhook = HandleBillingWebhookUseCase(plans=self.h.billing.plans, history=self.h.history)

    async def _stripe_says(self, event_id: str, status: str) -> None:
        self.h.billing.gateway.subscriptions["sub_1"] = _snapshot(status)
        self.h.billing.gateway.events[event_id] = BillingWebhookEvent(
            event_id=event_id,
            type="customer.subscription.updated",
            customer_id=CUSTOMER,
            subscription_id="sub_1",
            account_id=ACCOUNT,
        )
        await self.webhook.execute(b"{}", event_id)

    async def test_cancel_starts_the_window_and_it_expires(self) -> None:
        await self._stripe_says("evt_1", "canceled")
        status = await self.h.history.status(ACCOUNT)
        self.assertFalse(status.saving)
        self.assertEqual(status.expires_at, self.h.clock.now + timedelta(days=30))
        # Still readable, and nothing new is saved.
        self.assertEqual(len((await self.h.queries.list(_person())).items), 1)
        self.assertFalse(await self.h.history.save_completed(await self.h.finished_run("run-2")))

        self.h.clock.now += timedelta(days=29)
        self.assertEqual(await self.h.history.purge_expired(), 0)
        self.h.clock.now += timedelta(days=2)
        self.assertEqual(await self.h.history.purge_expired(), 1)
        self.assertEqual(await self.h.saved.count(ACCOUNT), 0)
        self.assertIsNone((await self.h.history.status(ACCOUNT)).expires_at)
        self.assertEqual(await self.h.history.purge_expired(), 0)  # idempotent

    async def test_a_repeat_webhook_keeps_the_first_expiry(self) -> None:
        await self._stripe_says("evt_1", "canceled")
        first = (await self.h.history.status(ACCOUNT)).expires_at
        self.h.clock.now += timedelta(days=3)
        await self._stripe_says("evt_2", "canceled")
        self.assertEqual((await self.h.history.status(ACCOUNT)).expires_at, first)

    async def test_resubscribing_restores_everything(self) -> None:
        await self._stripe_says("evt_1", "canceled")
        self.h.clock.now += timedelta(days=10)
        await self._stripe_says("evt_2", "active")
        status = await self.h.history.status(ACCOUNT)
        self.assertEqual((status.saving, status.expires_at), (True, None))
        self.h.clock.now += timedelta(days=60)
        self.h.billing.gateway.subscriptions["sub_1"] = _snapshot(end=self.h.clock.now + timedelta(days=20))
        await self.h.billing.subscribe()
        self.assertEqual(await self.h.history.purge_expired(), 0)
        self.assertEqual(await self.h.saved.count(ACCOUNT), 1)

    async def test_purge_rechecks_the_plan(self) -> None:
        # The resubscribe's webhook has not been applied yet but the row is
        # paid again: the expiry is cleared, nothing removed.
        await self.h.saved.arm_expiry(ACCOUNT, self.h.clock.now - timedelta(seconds=1))
        self.assertEqual(await self.h.history.purge_expired(), 0)
        self.assertEqual(await self.h.saved.count(ACCOUNT), 1)
        self.assertIsNone(await self.h.saved.expiry(ACCOUNT))

    async def test_past_due_does_not_start_the_window(self) -> None:
        await self._stripe_says("evt_1", "past_due")
        self.assertIsNone((await self.h.history.status(ACCOUNT)).expires_at)
        self.assertEqual(await self.h.history.arm_lapsed(), 0)

    async def test_the_cleanup_backstop_arms_a_missed_webhook(self) -> None:
        await self.h.subscribe("canceled")  # no webhook told the history
        self.assertIsNone((await self.h.history.status(ACCOUNT)).expires_at)
        self.assertEqual(await self.h.history.arm_lapsed(), 1)
        self.assertEqual(
            (await self.h.history.status(ACCOUNT)).expires_at, self.h.clock.now + timedelta(days=30)
        )
        self.assertEqual(await self.h.history.arm_lapsed(), 0)


class HoldAndCleanupTests(unittest.IsolatedAsyncioTestCase):
    """The deletion hold over the in-memory adapters: saved runs survive it,
    restore re-arms a fresh window, the cleanup removes it all after."""

    async def asyncSetUp(self) -> None:
        self.h = _History()
        self.directory = InMemoryAccountDirectory()
        self.keys = InMemoryApiKeyRepository()
        account = await self.directory.resolve_account("sub-1")
        self.account_id = account.account_id
        self.h.saved = InMemorySavedRuns(SETTINGS, accounts=self.directory)
        self.h.history.saved_runs = self.h.saved
        self.deleter = InMemoryAccountDeleter(
            SETTINGS,
            accounts=self.directory,
            api_keys=self.keys,
            billing_accounts=self.h.billing.accounts,
            saved_runs=self.h.saved,
        )
        await self.h.subscribe(account_id=self.account_id)
        await self.h.history.save_completed(await self.h.finished_run("run-1", account_id=self.account_id))
        self.person = Principal(
            subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id=self.account_id
        )
        self.cleanup = AccountCleanupUseCase(
            deleter=self.deleter, history=self.h.history, billing=self.h.billing.plans, clock=self.h.clock
        )

    async def _hold(self) -> None:
        # What DeleteAccountUseCase leaves: the subscription cancelled, the hold set.
        await self.h.subscribe("canceled", account_id=self.account_id)
        await self.deleter.schedule_deletion(
            "sub-1", now=self.h.clock.now, purge_at=self.h.clock.now + timedelta(days=30)
        )

    async def test_restore_keeps_the_saved_runs_with_a_fresh_window(self) -> None:
        await self._hold()
        self.h.clock.now += timedelta(days=20)
        # The hold protects them from the window scans.
        self.assertEqual(await self.h.history.arm_lapsed(), 0)

        restored = RestoreAccountUseCase(deleter=self.deleter, history=self.h.history, clock=self.h.clock)
        self.assertTrue(await restored.execute(self.person))

        self.assertEqual(await self.h.saved.count(self.account_id), 1)
        status = await self.h.history.status(self.account_id)
        self.assertEqual((status.saving, status.expires_at), (False, self.h.clock.now + timedelta(days=30)))

    async def test_the_cleanup_removes_the_account_and_its_saved_runs_after_the_hold(self) -> None:
        await self._hold()
        self.h.clock.now += timedelta(days=29)
        self.assertEqual((await self.cleanup.run()).accounts_removed, 0)
        self.assertEqual(await self.h.saved.count(self.account_id), 1)

        self.h.clock.now += timedelta(days=2)
        report = await self.cleanup.run()
        self.assertEqual(report.accounts_removed, 1)
        self.assertEqual(await self.h.saved.count(self.account_id), 0)
        self.assertIsNone(await self.h.billing.accounts.get(self.account_id))
        self.assertNotEqual((await self.directory.resolve_account("sub-1")).account_id, self.account_id)
        self.assertEqual((await self.cleanup.run()).accounts_removed, 0)

    async def test_a_live_subscription_is_cancelled_before_removal_or_the_account_is_skipped(self) -> None:
        await self.deleter.schedule_deletion(
            "sub-1", now=self.h.clock.now, purge_at=self.h.clock.now + timedelta(days=30)
        )
        self.h.clock.now += timedelta(days=31)
        self.h.billing.gateway.cancel_error = RuntimeError("stripe down")
        with self.assertLogs("videolens", "ERROR"):
            report = await self.cleanup.run()
        self.assertEqual((report.accounts_removed, report.accounts_skipped), (0, 1))
        self.assertEqual(await self.h.saved.count(self.account_id), 1)

        self.h.billing.gateway.cancel_error = None
        self.assertEqual((await self.cleanup.run()).accounts_removed, 1)
        self.assertEqual(self.h.billing.gateway.cancelled, ["sub_1"])

    async def test_the_cleanup_also_purges_expired_windows(self) -> None:
        await self.h.subscribe("canceled", account_id=self.account_id)
        self.assertEqual((await self.cleanup.run()).windows_started, 1)
        self.h.clock.now += timedelta(days=31)
        self.assertEqual((await self.cleanup.run()).saved_runs_removed, 1)


class CursorTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        from app.application.saved_history import decode_cursor

        cursor = SavedRunCursor(created_at=datetime(2026, 11, 14, 1, 2, 3, tzinfo=timezone.utc), saved_id="abc")
        self.assertEqual(decode_cursor(encode_cursor(cursor)), cursor)
        self.assertIsNone(decode_cursor(None))
        self.assertIsNone(encode_cursor(None))


if __name__ == "__main__":
    unittest.main()
