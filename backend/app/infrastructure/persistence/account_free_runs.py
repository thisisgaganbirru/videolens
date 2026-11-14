"""AccountFreeRunAllowance adapters: signed-in free runs, counted per account
per UTC calendar month (`FREE_RUNS_PER_ACCOUNT_MONTHLY`).

They live with the identity tables rather than in Redis because they belong
to the account: they follow the person across devices, have to survive a
Redis flush for the whole month, and go when the account goes (`ON DELETE
CASCADE`, plus an explicit delete in `SqlAccountDeleter`).

`SqlAccountFreeRuns` takes a run with one statement,
`INSERT ... ON CONFLICT (account_id, period) DO UPDATE SET used = used + 1
WHERE used < :limit RETURNING used`: no row back means the month is used up.
On Postgres the conflict path locks the row, so concurrent requests are
serialised on it and can never take an account past its limit. SQLite (tests)
runs the same statement.

The paid plan's included runs (`PAID_RUNS_PER_MONTH`, docs/backend/billing.md)
are counted on the same row with a bigger `limit`: one counter of shared-key
runs per account per month, whichever plan granted them.

`InMemoryAccountFreeRuns` is the counterpart for the in-memory account store
a local `uvicorn` without `DATABASE_URL` gets: there is no await between the
check and the increment, so it is atomic on the event loop.
"""

from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ...domain.entities import AccountFreeRunClaim, FreeRunScope, FreeRunStatus
from ...domain.policies import start_of_next_utc_month, utc_month
from ..config import Settings
from .database import Database, utcnow
from .schema import account_free_run_holds, account_free_runs

# Like the Redis holds' TTL: comfortably longer than any job can take, short
# enough that a hold a crashed worker never released does not linger.
_HOLD_MAX_AGE = timedelta(days=2)

Clock = Callable[[], datetime]


def _status(limit: int, used: int, now: datetime) -> FreeRunStatus:
    resets_at = start_of_next_utc_month(now)
    if limit <= 0:
        return FreeRunStatus(
            enabled=False, limit=0, used=0, remaining=0, resets_at=resets_at, scope=FreeRunScope.ACCOUNT
        )
    used = max(0, min(used, limit))
    return FreeRunStatus(
        enabled=True, limit=limit, used=used, remaining=limit - used, resets_at=resets_at, scope=FreeRunScope.ACCOUNT
    )


class SqlAccountFreeRuns:
    def __init__(self, settings: Settings, database: Database, *, clock: Clock | None = None) -> None:
        self._settings = settings
        self._db = database
        self._clock = clock or utcnow

    @property
    def enabled(self) -> bool:
        return self._db.enabled and self._settings.free_runs_per_account_monthly > 0

    @property
    def _limit(self) -> int:
        return self._settings.free_runs_per_account_monthly

    def _insert(self):
        return postgres_insert if self._db.dialect == "postgresql" else sqlite_insert

    def _limit_for(self, limit: int | None) -> int:
        """The limit a call counts against: an explicit one (the paid plan's
        included runs share this counter) needs only the store; the free one
        needs the allowance on. 0 = nothing to count against."""
        if limit is not None:
            return limit if self._db.enabled else 0
        return self._limit if self.enabled else 0

    async def status(self, account_id: str, *, limit: int | None = None) -> FreeRunStatus:
        now = self._clock()
        limit = self._limit_for(limit)
        if limit <= 0:
            return _status(0, 0, now)
        async with self._db.connect() as conn:
            used = await conn.scalar(
                select(account_free_runs.c.used).where(
                    account_free_runs.c.account_id == account_id,
                    account_free_runs.c.period == utc_month(now),
                )
            )
        return _status(limit, used or 0, now)

    async def try_consume(self, account_id: str, *, limit: int | None = None) -> AccountFreeRunClaim | None:
        limit = self._limit_for(limit)
        if limit <= 0:
            return None
        period = utc_month(self._clock())
        table = account_free_runs
        statement = (
            self._insert()(table)
            .values(account_id=account_id, period=period, used=1)
            .on_conflict_do_update(
                index_elements=[table.c.account_id, table.c.period],
                set_={"used": table.c.used + 1},
                where=table.c.used < limit,
            )
            .returning(table.c.used)
        )
        async with self._db.connect() as conn:
            taken = (await conn.execute(statement)).first()
        if taken is None:
            return None
        return AccountFreeRunClaim(account_id=account_id, period=period)

    async def refund(self, claim: AccountFreeRunClaim) -> None:
        async with self._db.connect() as conn:
            await self._decrement(conn, claim.account_id, claim.period)

    @staticmethod
    async def _decrement(conn, account_id: str, period: str) -> None:
        # Never below zero; a row that is gone (account deleted) stays gone.
        await conn.execute(
            update(account_free_runs)
            .where(
                account_free_runs.c.account_id == account_id,
                account_free_runs.c.period == period,
                account_free_runs.c.used > 0,
            )
            .values(used=account_free_runs.c.used - 1)
        )

    async def hold(self, run_id: str, claim: AccountFreeRunClaim) -> None:
        now = self._clock()
        async with self._db.connect() as conn:
            await conn.execute(delete(account_free_run_holds).where(account_free_run_holds.c.created_at < now - _HOLD_MAX_AGE))
            await conn.execute(
                account_free_run_holds.insert().values(
                    run_id=run_id, account_id=claim.account_id, period=claim.period, created_at=now
                )
            )

    async def release(self, run_id: str, *, refund: bool) -> bool:
        async with self._db.connect() as conn:
            row = (
                await conn.execute(
                    select(account_free_run_holds.c.account_id, account_free_run_holds.c.period).where(
                        account_free_run_holds.c.run_id == run_id
                    )
                )
            ).first()
            if row is None:
                return False
            # Of two racing releases only one deletes the row (the other
            # waits on its lock, then matches nothing), so a run is handed
            # back at most once.
            removed = await conn.execute(delete(account_free_run_holds).where(account_free_run_holds.c.run_id == run_id))
            if removed.rowcount != 1 or not refund:
                return False
            await self._decrement(conn, row.account_id, row.period)
        return True

    async def close(self) -> None:
        # The engine belongs to `Database`, closed by the container.
        return None


class InMemoryAccountFreeRuns:
    def __init__(self, settings: Settings, *, enabled: bool = True, clock: Clock | None = None) -> None:
        self._settings = settings
        self._enabled = enabled
        self._clock = clock or utcnow
        self._used: dict[tuple[str, str], int] = {}
        self._held: dict[str, AccountFreeRunClaim] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled and self._settings.free_runs_per_account_monthly > 0

    def _limit_for(self, limit: int | None) -> int:
        # As SqlAccountFreeRuns._limit_for.
        if limit is not None:
            return limit if self._enabled else 0
        return self._settings.free_runs_per_account_monthly if self.enabled else 0

    async def status(self, account_id: str, *, limit: int | None = None) -> FreeRunStatus:
        now = self._clock()
        limit = self._limit_for(limit)
        if limit <= 0:
            return _status(0, 0, now)
        return _status(limit, self._used.get((account_id, utc_month(now)), 0), now)

    async def try_consume(self, account_id: str, *, limit: int | None = None) -> AccountFreeRunClaim | None:
        limit = self._limit_for(limit)
        if limit <= 0:
            return None
        key = (account_id, utc_month(self._clock()))
        if self._used.get(key, 0) >= limit:
            return None
        self._used[key] = self._used.get(key, 0) + 1
        return AccountFreeRunClaim(account_id=key[0], period=key[1])

    async def refund(self, claim: AccountFreeRunClaim) -> None:
        key = (claim.account_id, claim.period)
        if self._used.get(key, 0) > 0:
            self._used[key] -= 1

    async def hold(self, run_id: str, claim: AccountFreeRunClaim) -> None:
        self._held[run_id] = claim

    async def release(self, run_id: str, *, refund: bool) -> bool:
        claim = self._held.pop(run_id, None)
        if claim is None or not refund:
            return False
        await self.refund(claim)
        return True

    def forget_account(self, account_id: str) -> None:
        """Account deletion (`InMemoryAccountDeleter`): drop its usage and
        holds, as the SQL foreign keys' cascade does."""
        self._used = {key: used for key, used in self._used.items() if key[0] != account_id}
        self._held = {run_id: claim for run_id, claim in self._held.items() if claim.account_id != account_id}

    async def close(self) -> None:
        return None
