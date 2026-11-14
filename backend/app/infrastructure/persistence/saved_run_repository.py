"""SavedRunRepository adapters: a paid account's saved runs
(docs/backend/saved-history.md, migration `0006_saved_history`).

`SqlSavedRuns` is the deployed one (Postgres via asyncpg, SQLite in tests):
rows in `saved_runs`, the post-cancel expiry in
`accounts.saved_runs_expire_at`. `InMemorySavedRuns` is what a local
`uvicorn` without `DATABASE_URL` gets (lost on restart), and, constructed
with `enabled=False`, the "nothing is saved" stand-in for a distributed
deployment without a database.

Every query names the account: there is no read or write by run id alone,
so one account can never reach another's rows. Saving is idempotent on the
`(account_id, run_id)` unique constraint (`INSERT ... ON CONFLICT DO
NOTHING`), so a retried job or a duplicate completion never writes twice.
"""

import json
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ...domain.entities import (
    SavedRun,
    SavedRunCursor,
    SavedRunPage,
    SavedRunSource,
    SavedRunSummary,
)
from ...domain.policies import (
    PAID_SUBSCRIPTION_STATUSES,
    SUBSCRIPTION_RENEWAL_GRACE,
    UNSETTLED_SUBSCRIPTION_STATUSES,
)
from ..config import Settings
from .database import Database, as_utc
from .schema import accounts, billing_accounts, saved_runs


def _result_bytes(result: dict) -> int:
    return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _summary(row) -> SavedRunSummary:
    return SavedRunSummary(
        run_id=row.run_id,
        title=row.title,
        summary_snippet=row.summary_snippet,
        source=SavedRunSource.from_dict(row.source),
        completeness=row.completeness,
        created_at=as_utc(row.created_at),
        saved_id=row.id,
        thumbnail=row.thumbnail,
    )


def _full(row) -> SavedRun:
    return SavedRun(
        run_id=row.run_id,
        account_id=row.account_id,
        title=row.title,
        summary_snippet=row.summary_snippet,
        source=SavedRunSource.from_dict(row.source),
        result=row.result,
        completeness=row.completeness,
        created_at=as_utc(row.created_at),
        saved_id=row.id,
        thumbnail=row.thumbnail,
    )


_LIGHT_COLUMNS = (
    saved_runs.c.id,
    saved_runs.c.run_id,
    saved_runs.c.title,
    saved_runs.c.summary_snippet,
    saved_runs.c.source,
    saved_runs.c.completeness,
    saved_runs.c.created_at,
    saved_runs.c.thumbnail,
)


class SqlSavedRuns:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._db = database

    @property
    def enabled(self) -> bool:
        return self._db.enabled

    def _insert(self):
        return postgres_insert if self._db.dialect == "postgresql" else sqlite_insert

    def _locked(self, query):
        # Row locks are Postgres-only; SQLite serialises writers anyway.
        return query.with_for_update() if self._db.dialect == "postgresql" else query

    async def save(self, run: SavedRun) -> bool:
        statement = (
            self._insert()(saved_runs)
            .values(
                id=run.saved_id or str(uuid.uuid4()),
                account_id=run.account_id,
                run_id=run.run_id,
                title=run.title[:500],
                summary_snippet=(run.summary_snippet or None) and run.summary_snippet[:400],
                completeness=run.completeness,
                source=run.source.to_dict(),
                result=run.result,
                result_bytes=_result_bytes(run.result),
                thumbnail=run.thumbnail or None,
                created_at=run.created_at,
            )
            .on_conflict_do_nothing(index_elements=["account_id", "run_id"])
        )
        async with self._db.connect() as conn:
            inserted = await conn.execute(statement)
        return inserted.rowcount == 1

    async def list_page(
        self, account_id: str, *, limit: int, before: Optional[SavedRunCursor] = None
    ) -> SavedRunPage:
        query = select(*_LIGHT_COLUMNS).where(saved_runs.c.account_id == account_id)
        if before is not None:
            query = query.where(
                or_(
                    saved_runs.c.created_at < before.created_at,
                    and_(saved_runs.c.created_at == before.created_at, saved_runs.c.id < before.saved_id),
                )
            )
        query = query.order_by(saved_runs.c.created_at.desc(), saved_runs.c.id.desc()).limit(limit + 1)
        async with self._db.connect() as conn:
            rows = (await conn.execute(query)).all()
        items = [_summary(row) for row in rows[:limit]]
        cursor = None
        if len(rows) > limit and items:
            last = items[-1]
            cursor = SavedRunCursor(created_at=last.created_at, saved_id=last.saved_id)
        return SavedRunPage(items=items, next_cursor=cursor)

    async def get(self, account_id: str, run_id: str) -> Optional[SavedRun]:
        async with self._db.connect() as conn:
            row = (
                await conn.execute(
                    select(saved_runs).where(saved_runs.c.account_id == account_id, saved_runs.c.run_id == run_id)
                )
            ).first()
        return _full(row) if row is not None else None

    async def delete(self, account_id: str, run_id: str) -> bool:
        async with self._db.connect() as conn:
            gone = await conn.execute(
                delete(saved_runs).where(saved_runs.c.account_id == account_id, saved_runs.c.run_id == run_id)
            )
        return gone.rowcount == 1

    async def delete_all(self, account_id: str) -> int:
        async with self._db.connect() as conn:
            gone = await conn.execute(delete(saved_runs).where(saved_runs.c.account_id == account_id))
        return int(gone.rowcount or 0)

    async def expiry(self, account_id: str) -> Optional[datetime]:
        async with self._db.connect() as conn:
            value = await conn.scalar(select(accounts.c.saved_runs_expire_at).where(accounts.c.id == account_id))
        return as_utc(value)

    async def arm_expiry(self, account_id: str, expire_at: datetime, *, replace: bool = False) -> Optional[datetime]:
        condition = accounts.c.id == account_id
        if not replace:
            condition = and_(condition, accounts.c.saved_runs_expire_at.is_(None))
        async with self._db.connect() as conn:
            await conn.execute(update(accounts).where(condition).values(saved_runs_expire_at=expire_at))
            value = await conn.scalar(select(accounts.c.saved_runs_expire_at).where(accounts.c.id == account_id))
        return as_utc(value)

    async def clear_expiry(self, account_id: str) -> None:
        async with self._db.connect() as conn:
            await conn.execute(
                update(accounts)
                .where(accounts.c.id == account_id, accounts.c.saved_runs_expire_at.is_not(None))
                .values(saved_runs_expire_at=None)
            )

    async def accounts_to_arm(self, now: datetime, *, limit: int) -> list[str]:
        # The SQL half of `policies.subscription_has_ended`, so paid accounts
        # are never scanned (they would crowd out the ones that need it);
        # the caller re-checks each candidate with the policy itself.
        status = billing_accounts.c.status
        not_paid = or_(
            billing_accounts.c.account_id.is_(None),
            status.is_(None),
            status.not_in(sorted(PAID_SUBSCRIPTION_STATUSES | UNSETTLED_SUBSCRIPTION_STATUSES)),
            and_(
                status.in_(sorted(PAID_SUBSCRIPTION_STATUSES)),
                billing_accounts.c.current_period_end.is_not(None),
                billing_accounts.c.current_period_end < now - SUBSCRIPTION_RENEWAL_GRACE,
            ),
        )
        has_runs = select(saved_runs.c.account_id).where(saved_runs.c.account_id == accounts.c.id).exists()
        query = (
            select(accounts.c.id)
            .select_from(accounts.outerjoin(billing_accounts, billing_accounts.c.account_id == accounts.c.id))
            .where(
                accounts.c.saved_runs_expire_at.is_(None),
                accounts.c.purge_at.is_(None),
                has_runs,
                not_paid,
            )
            .order_by(accounts.c.id)
            .limit(limit)
        )
        async with self._db.connect() as conn:
            rows = (await conn.execute(query)).all()
        return [row.id for row in rows]

    async def expired_accounts(self, now: datetime, *, limit: int) -> list[str]:
        async with self._db.connect() as conn:
            rows = (
                await conn.execute(
                    select(accounts.c.id)
                    .where(
                        accounts.c.saved_runs_expire_at.is_not(None),
                        accounts.c.saved_runs_expire_at <= now,
                        accounts.c.purge_at.is_(None),
                    )
                    .order_by(accounts.c.saved_runs_expire_at)
                    .limit(limit)
                )
            ).all()
        return [row.id for row in rows]

    async def purge_expired(self, account_id: str, now: datetime) -> int:
        async with self._db.connect() as conn:
            due = await conn.scalar(
                self._locked(
                    select(accounts.c.id).where(
                        accounts.c.id == account_id,
                        accounts.c.saved_runs_expire_at.is_not(None),
                        accounts.c.saved_runs_expire_at <= now,
                        accounts.c.purge_at.is_(None),
                    )
                )
            )
            if due is None:
                return 0
            gone = await conn.execute(delete(saved_runs).where(saved_runs.c.account_id == account_id))
            await conn.execute(update(accounts).where(accounts.c.id == account_id).values(saved_runs_expire_at=None))
        return int(gone.rowcount or 0)

    async def count(self, account_id: str) -> int:
        """Tests and operators: how many runs the account has saved."""
        async with self._db.connect() as conn:
            value = await conn.scalar(
                select(func.count()).select_from(saved_runs).where(saved_runs.c.account_id == account_id)
            )
        return int(value or 0)


class InMemorySavedRuns:
    """Process-local saved runs, same semantics as the SQL adapter. The
    deletion hold and the billing state it cannot see on its own come from
    the in-memory account directory (`pending`) when one is given; the
    application re-checks the paid-plan rule for `accounts_to_arm`."""

    def __init__(self, settings: Settings, *, enabled: bool = True, accounts=None) -> None:
        self._settings = settings
        self._enabled = enabled
        self._accounts = accounts
        self._rows: dict[str, dict[str, SavedRun]] = {}
        self._expiry: dict[str, datetime] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _pending(self, account_id: str) -> bool:
        return self._accounts is not None and self._accounts.is_pending(account_id)

    async def save(self, run: SavedRun) -> bool:
        mine = self._rows.setdefault(run.account_id, {})
        if run.run_id in mine:
            return False
        mine[run.run_id] = SavedRun(**{**run.__dict__, "saved_id": run.saved_id or str(uuid.uuid4())})
        return True

    def _ordered(self, account_id: str) -> list[SavedRun]:
        return sorted(
            self._rows.get(account_id, {}).values(), key=lambda r: (r.created_at, r.saved_id), reverse=True
        )

    async def list_page(
        self, account_id: str, *, limit: int, before: Optional[SavedRunCursor] = None
    ) -> SavedRunPage:
        rows = self._ordered(account_id)
        if before is not None:
            rows = [r for r in rows if (r.created_at, r.saved_id) < (before.created_at, before.saved_id)]
        items = [
            SavedRunSummary(
                run_id=r.run_id,
                title=r.title,
                summary_snippet=r.summary_snippet,
                source=r.source,
                completeness=r.completeness,
                created_at=r.created_at,
                saved_id=r.saved_id,
                thumbnail=r.thumbnail,
            )
            for r in rows[:limit]
        ]
        cursor = None
        if len(rows) > limit and items:
            cursor = SavedRunCursor(created_at=items[-1].created_at, saved_id=items[-1].saved_id)
        return SavedRunPage(items=items, next_cursor=cursor)

    async def get(self, account_id: str, run_id: str) -> Optional[SavedRun]:
        return self._rows.get(account_id, {}).get(run_id)

    async def delete(self, account_id: str, run_id: str) -> bool:
        return self._rows.get(account_id, {}).pop(run_id, None) is not None

    async def delete_all(self, account_id: str) -> int:
        return len(self._rows.pop(account_id, {}))

    async def expiry(self, account_id: str) -> Optional[datetime]:
        return self._expiry.get(account_id)

    async def arm_expiry(self, account_id: str, expire_at: datetime, *, replace: bool = False) -> Optional[datetime]:
        if replace or account_id not in self._expiry:
            self._expiry[account_id] = expire_at
        return self._expiry[account_id]

    async def clear_expiry(self, account_id: str) -> None:
        self._expiry.pop(account_id, None)

    async def accounts_to_arm(self, now: datetime, *, limit: int) -> list[str]:
        candidates = [
            account_id
            for account_id, rows in sorted(self._rows.items())
            if rows and account_id not in self._expiry and not self._pending(account_id)
        ]
        return candidates[:limit]

    async def expired_accounts(self, now: datetime, *, limit: int) -> list[str]:
        due = sorted(
            (expire_at, account_id)
            for account_id, expire_at in self._expiry.items()
            if expire_at <= now and not self._pending(account_id)
        )
        return [account_id for _, account_id in due[:limit]]

    async def purge_expired(self, account_id: str, now: datetime) -> int:
        expire_at = self._expiry.get(account_id)
        if expire_at is None or expire_at > now or self._pending(account_id):
            return 0
        del self._expiry[account_id]
        return len(self._rows.pop(account_id, {}))

    async def count(self, account_id: str) -> int:
        return len(self._rows.get(account_id, {}))

    def forget_account(self, account_id: str) -> None:
        """Account removal (`InMemoryAccountDeleter`), as the SQL cascade."""
        self._rows.pop(account_id, None)
        self._expiry.pop(account_id, None)

    async def close(self) -> None:
        return None
