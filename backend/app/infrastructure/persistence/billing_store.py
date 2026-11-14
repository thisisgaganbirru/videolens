"""BillingAccounts and ExtraRunLedger adapters (docs/backend/billing.md).

SQL (Postgres via asyncpg, SQLite in tests) beside the identity tables, or
in process memory for a local `uvicorn` without `DATABASE_URL`. Both belong
to the account (`ON DELETE CASCADE`, plus an explicit delete in
`SqlAccountDeleter`), never to a run: runs stay in Redis and history in the
browser. A ledger row holds a run id, an account id, a Stripe customer id
and timestamps, nothing about the media or the result.

Exactly-once extra-run billing rests on two conditional writes:
`complete` moves a row `held -> due` only when it is still held, and `void`
moves it `held -> void` only when it is still held, so of a worker
finishing a run and the stale-run check failing it, exactly one wins and a
run that did not complete can never become due.
"""

from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ...domain.entities import BillingAccount, ExtraRunCharge, SubscriptionSnapshot
from ...domain.policies import subscription_is_live
from ..config import Settings
from .database import Database, as_utc, utcnow
from .schema import billing_accounts, billing_events, billing_extra_runs

Clock = Callable[[], datetime]

# Stripe retries a webhook for up to three days; a month of ids is plenty.
_EVENT_MAX_AGE = timedelta(days=30)
# A held row older than this belongs to a run that can no longer finish
# (the long job timeout is 30 minutes); it is voided, never billed.
_HOLD_MAX_AGE = timedelta(days=2)
# Stripe accepts meter events up to 35 days old; anything older stays due
# (and unbilled) rather than be refused forever on every retry.
_REPORT_MAX_AGE = timedelta(days=34)

HELD, DUE, REPORTED, VOID = "held", "due", "reported", "void"


def _account_from_row(row) -> BillingAccount:
    return BillingAccount(
        account_id=row.account_id,
        stripe_customer_id=row.stripe_customer_id,
        stripe_subscription_id=row.stripe_subscription_id,
        status=row.status,
        price_id=row.price_id,
        interval=row.interval,
        current_period_end=as_utc(row.current_period_end),
        cancel_at_period_end=bool(row.cancel_at_period_end),
        updated_at=as_utc(row.updated_at),
    )


def _should_apply(current: BillingAccount, snapshot: SubscriptionSnapshot) -> bool:
    """A different subscription than the stored one replaces it unless the
    stored one is still live and the new one is not (an old, cancelled
    subscription's late event must not overwrite the current one)."""
    if not current.stripe_subscription_id or current.stripe_subscription_id == snapshot.subscription_id:
        return True
    return subscription_is_live(snapshot.status) or not subscription_is_live(current.status)


def _subscription_values(snapshot: SubscriptionSnapshot, now: datetime) -> dict:
    return {
        "stripe_subscription_id": snapshot.subscription_id,
        "status": snapshot.status,
        "price_id": snapshot.price_id,
        "interval": snapshot.interval,
        "current_period_end": snapshot.current_period_end,
        "cancel_at_period_end": snapshot.cancel_at_period_end,
        "updated_at": now,
    }


class SqlBillingAccounts:
    def __init__(self, settings: Settings, database: Database, *, clock: Clock | None = None) -> None:
        self._settings = settings
        self._db = database
        self._clock = clock or utcnow

    @property
    def enabled(self) -> bool:
        return self._db.enabled

    def _insert(self):
        return postgres_insert if self._db.dialect == "postgresql" else sqlite_insert

    async def get(self, account_id: str) -> Optional[BillingAccount]:
        async with self._db.connect() as conn:
            row = (await conn.execute(select(billing_accounts).where(billing_accounts.c.account_id == account_id))).first()
        return _account_from_row(row) if row is not None else None

    async def by_customer(self, customer_id: str) -> Optional[BillingAccount]:
        async with self._db.connect() as conn:
            row = (
                await conn.execute(select(billing_accounts).where(billing_accounts.c.stripe_customer_id == customer_id))
            ).first()
        return _account_from_row(row) if row is not None else None

    async def link_customer(self, account_id: str, customer_id: str) -> BillingAccount:
        statement = (
            self._insert()(billing_accounts)
            .values(account_id=account_id, stripe_customer_id=customer_id, cancel_at_period_end=False, updated_at=self._clock())
            .on_conflict_do_nothing()
        )
        async with self._db.connect() as conn:
            await conn.execute(statement)
            row = (await conn.execute(select(billing_accounts).where(billing_accounts.c.account_id == account_id))).first()
        if row is None:
            # The customer id is already another account's: never share it.
            raise RuntimeError("Stripe customer is linked to another account")
        return _account_from_row(row)

    async def apply_subscription(self, account_id: str, snapshot: SubscriptionSnapshot) -> bool:
        async with self._db.connect() as conn:
            row = (
                await conn.execute(
                    select(billing_accounts).where(billing_accounts.c.account_id == account_id).with_for_update()
                )
            ).first()
            if row is None or not _should_apply(_account_from_row(row), snapshot):
                return False
            await conn.execute(
                update(billing_accounts)
                .where(billing_accounts.c.account_id == account_id)
                .values(**_subscription_values(snapshot, self._clock()))
            )
        return True

    async def event_seen(self, event_id: str) -> bool:
        async with self._db.connect() as conn:
            found = await conn.scalar(select(billing_events.c.event_id).where(billing_events.c.event_id == event_id))
        return found is not None

    async def mark_event(self, event_id: str, event_type: str) -> None:
        now = self._clock()
        async with self._db.connect() as conn:
            await conn.execute(delete(billing_events).where(billing_events.c.received_at < now - _EVENT_MAX_AGE))
            await conn.execute(
                self._insert()(billing_events)
                .values(event_id=event_id, event_type=event_type[:100], received_at=now)
                .on_conflict_do_nothing()
            )

    async def close(self) -> None:
        return None


class SqlExtraRunLedger:
    def __init__(self, settings: Settings, database: Database, *, clock: Clock | None = None) -> None:
        self._settings = settings
        self._db = database
        self._clock = clock or utcnow

    async def hold(self, run_id: str, *, account_id: str, customer_id: str, period: str) -> None:
        now = self._clock()
        table = billing_extra_runs
        async with self._db.connect() as conn:
            await conn.execute(
                update(table).where(table.c.state == HELD, table.c.created_at < now - _HOLD_MAX_AGE).values(state=VOID)
            )
            await conn.execute(
                table.insert().values(
                    run_id=run_id,
                    account_id=account_id,
                    stripe_customer_id=customer_id,
                    period=period,
                    state=HELD,
                    created_at=now,
                )
            )

    async def count(self, account_id: str, period: str) -> int:
        table = billing_extra_runs
        async with self._db.connect() as conn:
            value = await conn.scalar(
                select(func.count())
                .select_from(table)
                .where(table.c.account_id == account_id, table.c.period == period, table.c.state != VOID)
            )
        return int(value or 0)

    async def complete(self, run_id: str) -> Optional[ExtraRunCharge]:
        now = self._clock()
        table = billing_extra_runs
        async with self._db.connect() as conn:
            moved = await conn.execute(
                update(table).where(table.c.run_id == run_id, table.c.state == HELD).values(state=DUE, completed_at=now)
            )
            if moved.rowcount != 1:
                return None
            row = (await conn.execute(select(table).where(table.c.run_id == run_id))).first()
        return ExtraRunCharge(
            run_id=row.run_id,
            account_id=row.account_id,
            stripe_customer_id=row.stripe_customer_id,
            completed_at=as_utc(row.completed_at),
        )

    async def void(self, run_id: str) -> bool:
        table = billing_extra_runs
        async with self._db.connect() as conn:
            moved = await conn.execute(update(table).where(table.c.run_id == run_id, table.c.state == HELD).values(state=VOID))
        return moved.rowcount == 1

    async def due(self, *, limit: int = 50) -> list[ExtraRunCharge]:
        table = billing_extra_runs
        oldest = self._clock() - _REPORT_MAX_AGE
        async with self._db.connect() as conn:
            rows = (
                await conn.execute(
                    select(table)
                    .where(table.c.state == DUE, table.c.completed_at >= oldest)
                    .order_by(table.c.completed_at)
                    .limit(limit)
                )
            ).all()
        return [
            ExtraRunCharge(
                run_id=row.run_id,
                account_id=row.account_id,
                stripe_customer_id=row.stripe_customer_id,
                completed_at=as_utc(row.completed_at),
            )
            for row in rows
        ]

    async def mark_reported(self, run_id: str) -> None:
        table = billing_extra_runs
        async with self._db.connect() as conn:
            await conn.execute(
                update(table)
                .where(table.c.run_id == run_id, table.c.state == DUE)
                .values(state=REPORTED, reported_at=self._clock())
            )


class InMemoryBillingAccounts:
    """For a local API without DATABASE_URL (and off in distributed mode
    without one, where `Settings.distributed_billing_error` refuses to start
    anyway). Lost on restart, like the in-memory accounts it sits beside."""

    def __init__(self, settings: Settings, *, enabled: bool = True, clock: Clock | None = None) -> None:
        self._settings = settings
        self._enabled = enabled
        self._clock = clock or utcnow
        self._rows: dict[str, BillingAccount] = {}
        self._events: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def get(self, account_id: str) -> Optional[BillingAccount]:
        return self._rows.get(account_id)

    async def by_customer(self, customer_id: str) -> Optional[BillingAccount]:
        return next((row for row in self._rows.values() if row.stripe_customer_id == customer_id), None)

    async def link_customer(self, account_id: str, customer_id: str) -> BillingAccount:
        existing = self._rows.get(account_id)
        if existing is not None:
            return existing
        if await self.by_customer(customer_id) is not None:
            raise RuntimeError("Stripe customer is linked to another account")
        row = BillingAccount(account_id=account_id, stripe_customer_id=customer_id, updated_at=self._clock())
        self._rows[account_id] = row
        return row

    async def apply_subscription(self, account_id: str, snapshot: SubscriptionSnapshot) -> bool:
        current = self._rows.get(account_id)
        if current is None or not _should_apply(current, snapshot):
            return False
        self._rows[account_id] = BillingAccount(
            account_id=account_id, stripe_customer_id=current.stripe_customer_id, **_subscription_values(snapshot, self._clock())
        )
        return True

    async def event_seen(self, event_id: str) -> bool:
        return event_id in self._events

    async def mark_event(self, event_id: str, event_type: str) -> None:
        self._events.setdefault(event_id, self._clock())

    def forget_account(self, account_id: str) -> None:
        """Account deletion (`InMemoryAccountDeleter`), as the SQL cascade."""
        self._rows.pop(account_id, None)

    async def close(self) -> None:
        return None


class InMemoryExtraRunLedger:
    def __init__(self, settings: Settings, *, clock: Clock | None = None) -> None:
        self._settings = settings
        self._clock = clock or utcnow
        # run_id -> [account_id, customer_id, period, state, completed_at]
        self._rows: dict[str, list] = {}

    async def hold(self, run_id: str, *, account_id: str, customer_id: str, period: str) -> None:
        self._rows[run_id] = [account_id, customer_id, period, HELD, None]

    async def count(self, account_id: str, period: str) -> int:
        return sum(1 for row in self._rows.values() if row[0] == account_id and row[2] == period and row[3] != VOID)

    async def complete(self, run_id: str) -> Optional[ExtraRunCharge]:
        row = self._rows.get(run_id)
        if row is None or row[3] != HELD:
            return None
        row[3], row[4] = DUE, self._clock()
        return ExtraRunCharge(run_id=run_id, account_id=row[0], stripe_customer_id=row[1], completed_at=row[4])

    async def void(self, run_id: str) -> bool:
        row = self._rows.get(run_id)
        if row is None or row[3] != HELD:
            return False
        row[3] = VOID
        return True

    async def due(self, *, limit: int = 50) -> list[ExtraRunCharge]:
        return [
            ExtraRunCharge(run_id=run_id, account_id=row[0], stripe_customer_id=row[1], completed_at=row[4])
            for run_id, row in self._rows.items()
            if row[3] == DUE
        ][:limit]

    async def mark_reported(self, run_id: str) -> None:
        row = self._rows.get(run_id)
        if row is not None and row[3] == DUE:
            row[3] = REPORTED

    def state(self, run_id: str) -> str | None:
        row = self._rows.get(run_id)
        return row[3] if row is not None else None

    def forget_account(self, account_id: str) -> None:
        self._rows = {run_id: row for run_id, row in self._rows.items() if row[0] != account_id}
