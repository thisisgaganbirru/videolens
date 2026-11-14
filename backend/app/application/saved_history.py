"""Saved history: a paid account's run results kept on the server
(docs/backend/saved-history.md; owner decision 2026-11-14).

`SavedHistory` holds the rules every caller shares:

- Saving. When a run succeeds and its account is on the paid plan right
  then, its result is saved once (`save_completed`, called by the pipeline
  right after the result is stored and the extra run billed). Idempotent on
  the run id; a failure is logged and never fails, un-bills or refunds the
  run. Result text, a source descriptor and the run's small poster
  thumbnail (`thumbnail`, as the live run exposes it): no other media,
  never a key.
- The post-cancel window. Once the paid plan has ended
  (`policies.subscription_has_ended`) the account's saved runs stay
  readable and deletable for `PAID_SAVED_RUNS_GRACE_DAYS`, then the cleanup
  job removes them. A webhook arms or clears the expiry as soon as Stripe
  reports the change (`sync_expiry`); the cleanup job arms any the webhook
  missed (`arm_lapsed`). A resubscribe inside the window clears it.

`SavedHistoryQueries` is the API side: list, get, delete one, delete all,
always for the caller's own account.

Complimentary Plus (`accounts.complimentary_plus`, docs/backend/billing.md)
is the paid plan here too: its runs are saved and `saving` is true with or
without Stripe, and it never gets a post-cancel window (one is cleared).

Saving is off (nothing saved, every list empty, `saving: false`) without a
database, or with billing off and no account store to read complimentary
Plus from, which is exactly the behaviour before this existed. The
post-cancel window (arming, purging, the restore re-arm, the expiry shown)
needs Stripe billing on, as before: with it off nothing is armed or
removed, so switching Stripe off never starts deleting anyone's runs.
"""

import base64
import binascii
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..domain.entities import (
    Principal,
    Run,
    RunStatus,
    SavedHistoryStatus,
    SavedRun,
    SavedRunCursor,
    SavedRunPage,
    SavedRunSource,
)
from ..domain.errors import InvalidCursorError, SavedRunNotFoundError
from ..domain.policies import subscription_grants_paid, subscription_has_ended
from ..domain.ports import RunRepository, SavedRunRepository
from ..domain.run_facts import describe_run, summary_snippet
from .billing import BillingPlans

logger = logging.getLogger("videolens")

Clock = Callable[[], datetime]

# Segment lists are the bulk of a large result and are derivable from
# nothing else, but the transcript and on-screen text they time are kept as
# text, so dropping them is the one trim that loses no words.
_SEGMENT_FIELDS = ("transcript_segments", "screen_text_segments")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_bytes(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _saved_bytes(result: dict, thumbnail: str | None) -> int:
    """What the size guard measures: the result as compact UTF-8 JSON plus
    the poster data URL (ASCII), so both count toward the one limit."""
    return _json_bytes(result) + len((thumbnail or "").encode("utf-8"))


def encode_cursor(cursor: SavedRunCursor | None) -> str | None:
    if cursor is None:
        return None
    raw = f"{cursor.created_at.isoformat()}|{cursor.saved_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> SavedRunCursor | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        created, saved_id = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").split("|", 1)
        created_at = datetime.fromisoformat(created)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidCursorError("That page of your history could not be found. Reload and try again.") from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return SavedRunCursor(created_at=created_at, saved_id=saved_id[:36])


class SavedHistory:
    def __init__(
        self,
        *,
        runs: RunRepository,
        saved_runs: SavedRunRepository,
        plans: BillingPlans | None,
        grace_days: int = 30,
        max_bytes: int = 2 * 1024 * 1024,
        clock: Clock | None = None,
    ) -> None:
        self._runs = runs
        self.saved_runs = saved_runs
        self._plans = plans
        self.grace = timedelta(days=max(0, grace_days))
        self.max_bytes = max(1, max_bytes)
        self._clock = clock or _utcnow

    @property
    def enabled(self) -> bool:
        """Saving can happen: a database to keep the rows in, and Stripe
        billing on or complimentary Plus readable to decide who is on the
        paid plan. Off = nothing is saved, as before."""
        return self.saved_runs.enabled and self._plans is not None and self._plans.offered

    @property
    def windows_enabled(self) -> bool:
        """The post-cancel window applies: a database and Stripe billing on
        (a subscription can end). Off = nothing is armed or removed."""
        return self.saved_runs.enabled and self._plans is not None and self._plans.enabled

    def now(self) -> datetime:
        return self._clock()

    # ------------------------------------------------------------ saving

    async def save_completed(self, run_id: str, *, source_url: str | None = None) -> bool:
        """Save the run's result if its account is on the paid plan now.
        True when this call saved it. Never raises."""
        if not self.enabled:
            return False
        try:
            run = await self._runs.get(run_id)
            if run is None or run.status is not RunStatus.COMPLETE or run.result is None or not run.account_id:
                return False
            assert self._plans is not None
            if not (await self._plans.standing(run.account_id)).paid:
                return False
            record = self._record(run, source_url)
            if record is None:
                return False
            saved = await self.saved_runs.save(record)
        except Exception:  # noqa: BLE001 - never fail or un-bill a finished run over saving
            logger.exception("Could not save run %s to its account's history", run_id)
            return False
        if saved:
            logger.info("Run %s saved to account %s's history", run_id, run.account_id)
        return saved

    def _record(self, run: Run, source_url: str | None) -> SavedRun | None:
        assert run.result is not None and run.account_id is not None
        facts = describe_run(run)
        metadata = run.source_metadata
        link = facts.source_kind == "link"
        source = SavedRunSource(
            source_kind=facts.source_kind,
            platform=facts.platform,
            source_url=(source_url or (metadata.source_url if metadata else None)) if link else None,
            source_title=metadata.title if metadata else None,
            uploader=metadata.uploader if metadata else None,
            duration_seconds=facts.duration_seconds,
            width=facts.width,
            height=facts.height,
        )
        result = run.result.model_dump(mode="json")
        thumbnail = run.thumbnail or None
        size = _saved_bytes(result, thumbnail)
        if size > self.max_bytes:
            # Over the guard: drop the segment lists first (they only time
            # text that is kept in full), then the poster, then give up.
            result = {key: value for key, value in result.items() if key not in _SEGMENT_FIELDS}
            dropped = ["segment lists"]
            if _saved_bytes(result, thumbnail) > self.max_bytes and thumbnail is not None:
                thumbnail = None
                dropped.append("poster")
            trimmed_size = _saved_bytes(result, thumbnail)
            if trimmed_size > self.max_bytes:
                logger.error(
                    "Run %s not saved to history: %d bytes (%d without segments and poster), over "
                    "PAID_SAVED_RUN_MAX_BYTES=%d",
                    run.run_id,
                    size,
                    trimmed_size,
                    self.max_bytes,
                )
                return None
            logger.warning(
                "Run %s saved without its %s: %d bytes, over PAID_SAVED_RUN_MAX_BYTES=%d",
                run.run_id,
                " and ".join(dropped),
                size,
                self.max_bytes,
            )
        return SavedRun(
            run_id=run.run_id,
            account_id=run.account_id,
            title=(run.result.title or "Untitled")[:500],
            summary_snippet=summary_snippet(run.result.summary),
            source=source,
            result=result,
            completeness=run.completeness.value,
            created_at=run.created_at,
            thumbnail=thumbnail,
        )

    # ---------------------------------------------------------- the window

    async def status(self, account_id: str | None) -> SavedHistoryStatus:
        if not account_id or not self.enabled:
            return SavedHistoryStatus()
        assert self._plans is not None
        if (await self._plans.standing(account_id)).paid:
            return SavedHistoryStatus(saving=True)
        if not self.windows_enabled:
            return SavedHistoryStatus()
        return SavedHistoryStatus(saving=False, expires_at=await self.saved_runs.expiry(account_id))

    async def sync_expiry(self, account_id: str) -> None:
        """After Stripe reported a subscription change: paid again clears the
        expiry (everything is kept); ended arms it, once, `grace` from now.
        In between (past_due, incomplete) nothing changes. Complimentary
        Plus counts as paid: a cancelled subscription on it arms nothing.
        Never raises."""
        if not self.windows_enabled:
            return
        assert self._plans is not None
        try:
            if await self._plans.is_complimentary(account_id):
                await self.saved_runs.clear_expiry(account_id)
                return
            account = await self._plans.accounts.get(account_id)
            now = self._clock()
            status = account.status if account else None
            period_end = account.current_period_end if account else None
            if subscription_grants_paid(status, period_end, now):
                await self.saved_runs.clear_expiry(account_id)
            elif subscription_has_ended(status, period_end, now):
                expires = await self.saved_runs.arm_expiry(account_id, now + self.grace)
                logger.info("Account %s saved runs are kept until %s", account_id, expires)
        except Exception:  # noqa: BLE001 - the cleanup job's backstop arms it later
            logger.exception("Could not update the saved-history window for account %s", account_id)

    async def rearm_after_restore(self, account_id: str) -> None:
        """A restored account comes back on the free plan (the subscription
        was cancelled at deletion): its saved runs get a fresh full window
        from now, so the hold never eats into it. A paid one (complimentary
        Plus included: the restore leaves the flag as it was) is untouched."""
        if not self.windows_enabled:
            return
        assert self._plans is not None
        try:
            if (await self._plans.standing(account_id)).paid:
                await self.saved_runs.clear_expiry(account_id)
                return
            if await self.saved_runs.expiry(account_id) is None:
                page = await self.saved_runs.list_page(account_id, limit=1)
                if not page.items:
                    return
            await self.saved_runs.arm_expiry(account_id, self._clock() + self.grace, replace=True)
        except Exception:  # noqa: BLE001 - the cleanup job's backstop arms it later
            logger.exception("Could not re-arm the saved-history window for restored account %s", account_id)

    async def arm_lapsed(self, *, limit: int = 200) -> int:
        """The cleanup job's backstop: accounts holding saved runs whose paid
        plan ended without a webhook saying so get their window now.
        Complimentary Plus is never armed (the scan skips it too)."""
        if not self.windows_enabled:
            return 0
        assert self._plans is not None
        now = self._clock()
        armed = 0
        for account_id in await self.saved_runs.accounts_to_arm(now, limit=limit):
            if await self._plans.is_complimentary(account_id):
                continue
            account = await self._plans.accounts.get(account_id)
            status = account.status if account else None
            period_end = account.current_period_end if account else None
            if not subscription_has_ended(status, period_end, now):
                continue
            await self.saved_runs.arm_expiry(account_id, now + self.grace)
            armed += 1
        if armed:
            logger.info("Saved-history window started for %d account(s) whose paid plan ended", armed)
        return armed

    async def purge_expired(self, *, limit: int = 25) -> int:
        """Remove saved runs whose window has passed. Re-checks the plan, so
        a resubscribe whose webhook has not been applied yet is not purged
        (its expiry is cleared instead), nor is complimentary Plus. Returns
        how many runs went."""
        if not self.windows_enabled:
            return 0
        assert self._plans is not None
        now = self._clock()
        removed = 0
        for account_id in await self.saved_runs.expired_accounts(now, limit=limit):
            if (await self._plans.standing(account_id)).paid:
                await self.saved_runs.clear_expiry(account_id)
                continue
            count = await self.saved_runs.purge_expired(account_id, now)
            removed += count
            logger.info("Removed %d saved run(s) of account %s: its paid plan ended", count, account_id)
        return removed


class SavedHistoryQueries:
    """`GET|DELETE /api/history`, `GET|DELETE /api/history/{run_id}`."""

    MAX_PAGE = 100

    def __init__(self, *, history: SavedHistory) -> None:
        self._history = history

    def _repo(self, principal: Principal) -> tuple[SavedRunRepository, str] | None:
        # Readable while there are rows to read, even with billing switched
        # off: deleting what you have must keep working.
        if not principal.account_id or not self._history.saved_runs.enabled:
            return None
        return self._history.saved_runs, principal.account_id

    async def status(self, principal: Principal) -> SavedHistoryStatus:
        return await self._history.status(principal.account_id)

    async def list(self, principal: Principal, *, limit: int = 20, cursor: str | None = None) -> SavedRunPage:
        before = decode_cursor(cursor)
        scoped = self._repo(principal)
        if scoped is None:
            return SavedRunPage(items=[])
        repo, account_id = scoped
        return await repo.list_page(account_id, limit=max(1, min(limit, self.MAX_PAGE)), before=before)

    async def get(self, principal: Principal, run_id: str) -> SavedRun:
        scoped = self._repo(principal)
        saved = await scoped[0].get(scoped[1], run_id) if scoped is not None else None
        if saved is None:
            raise SavedRunNotFoundError("That saved run was not found.")
        return saved

    async def delete(self, principal: Principal, run_id: str) -> None:
        scoped = self._repo(principal)
        if scoped is None or not await scoped[0].delete(scoped[1], run_id):
            raise SavedRunNotFoundError("That saved run was not found.")

    async def delete_all(self, principal: Principal) -> int:
        scoped = self._repo(principal)
        if scoped is None:
            return 0
        return await scoped[0].delete_all(scoped[1])
