"""AccountDirectory adapter over Postgres: accounts, workspaces, membership
and the subscription state a billing webhook writes."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import insert, select, update

from ...domain.entities import Account, Workspace
from ...domain.entitlements import Plan, entitlement_for
from .database import Database, as_utc, utcnow
from .schema import accounts, workspace_members, workspaces

# A free workspace's allowance renews on a rolling 30 days from creation;
# a paid one's period comes from the subscription itself.
FREE_PERIOD = timedelta(days=30)


class PostgresAccountDirectory:
    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def enabled(self) -> bool:
        return self._db.enabled

    @staticmethod
    def _account(row) -> Account:
        return Account(
            account_id=row.id,
            external_id=row.external_id,
            email=row.email,
            default_workspace_id=row.default_workspace_id,
            created_at=as_utc(row.created_at),
        )

    @staticmethod
    def _workspace(row) -> Workspace:
        return Workspace(
            workspace_id=row.id,
            name=row.name,
            owner_account_id=row.owner_account_id,
            plan=Plan(row.plan),
            seats=row.seats,
            stripe_customer_id=row.stripe_customer_id,
            stripe_subscription_id=row.stripe_subscription_id,
            minutes_included=row.minutes_included,
            minutes_used_period=Decimal("0"),
            period_start=as_utc(row.period_start),
            period_end=as_utc(row.period_end),
            max_duration_seconds=row.max_duration_seconds,
            created_at=as_utc(row.created_at),
        )

    async def resolve_account(self, external_id: str, email: str | None = None) -> Account:
        async with self._db.connect() as conn:
            row = (await conn.execute(select(accounts).where(accounts.c.external_id == external_id))).first()
            if row is not None:
                if email and row.email != email:
                    await conn.execute(
                        update(accounts).where(accounts.c.id == row.id).values(email=email)
                    )
                    row = (await conn.execute(select(accounts).where(accounts.c.id == row.id))).first()
                account = self._account(row)
                if account.default_workspace_id:
                    return account
                # An account without a workspace (a failed first boot, or a
                # row created by hand): give it one now.
                workspace_id = await self._create_personal_workspace(conn, account.account_id)
                await conn.execute(
                    update(accounts)
                    .where(accounts.c.id == account.account_id)
                    .values(default_workspace_id=workspace_id)
                )
                account.default_workspace_id = workspace_id
                return account

            now = utcnow()
            account_id = str(uuid.uuid4())
            await conn.execute(
                insert(accounts).values(
                    id=account_id,
                    external_id=external_id,
                    email=email,
                    default_workspace_id=None,
                    created_at=now,
                )
            )
            workspace_id = await self._create_personal_workspace(conn, account_id)
            await conn.execute(
                update(accounts).where(accounts.c.id == account_id).values(default_workspace_id=workspace_id)
            )
            return Account(
                account_id=account_id,
                external_id=external_id,
                email=email,
                default_workspace_id=workspace_id,
                created_at=now,
            )

    async def _create_personal_workspace(self, conn, account_id: str) -> str:
        now = utcnow()
        workspace_id = str(uuid.uuid4())
        free = entitlement_for(Plan.FREE)
        await conn.execute(
            insert(workspaces).values(
                id=workspace_id,
                name="Personal",
                owner_account_id=account_id,
                plan=Plan.FREE.value,
                seats=free.seats,
                minutes_included=free.minutes_included,
                period_start=now,
                period_end=now + FREE_PERIOD,
                created_at=now,
            )
        )
        await conn.execute(
            insert(workspace_members).values(workspace_id=workspace_id, account_id=account_id, role="owner")
        )
        return workspace_id

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            row = (await conn.execute(select(workspaces).where(workspaces.c.id == workspace_id))).first()
        if row is None:
            return None
        workspace = self._workspace(row)
        if workspace.plan is Plan.FREE and workspace.period_end <= utcnow():
            # Roll the free allowance forward lazily; nothing else ever
            # touches a free workspace's period.
            workspace = await self._roll_free_period(workspace)
        return workspace

    async def _roll_free_period(self, workspace: Workspace) -> Workspace:
        now = utcnow()
        start = workspace.period_end
        while start + FREE_PERIOD <= now:
            start += FREE_PERIOD
        async with self._db.connect() as conn:
            await conn.execute(
                update(workspaces)
                .where(workspaces.c.id == workspace.workspace_id)
                .values(period_start=start, period_end=start + FREE_PERIOD)
            )
        workspace.period_start = start
        workspace.period_end = start + FREE_PERIOD
        return workspace

    async def get_workspace_by_customer(self, stripe_customer_id: str) -> Optional[Workspace]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            row = (
                await conn.execute(
                    select(workspaces).where(workspaces.c.stripe_customer_id == stripe_customer_id)
                )
            ).first()
        return self._workspace(row) if row is not None else None

    async def list_workspaces(self, account_id: str) -> list[Workspace]:
        if not self.enabled:
            return []
        async with self._db.connect() as conn:
            rows = (
                await conn.execute(
                    select(workspaces)
                    .join(workspace_members, workspace_members.c.workspace_id == workspaces.c.id)
                    .where(workspace_members.c.account_id == account_id)
                    .order_by(workspaces.c.created_at)
                )
            ).all()
        return [self._workspace(row) for row in rows]

    async def member_role(self, workspace_id: str, account_id: str) -> Optional[str]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            return await conn.scalar(
                select(workspace_members.c.role).where(
                    workspace_members.c.workspace_id == workspace_id,
                    workspace_members.c.account_id == account_id,
                )
            )

    async def set_customer(self, workspace_id: str, stripe_customer_id: str) -> None:
        async with self._db.connect() as conn:
            await conn.execute(
                update(workspaces)
                .where(workspaces.c.id == workspace_id)
                .values(stripe_customer_id=stripe_customer_id)
            )

    async def apply_subscription(
        self,
        workspace_id: str,
        *,
        plan: Plan,
        minutes_included: int,
        period_start: datetime,
        period_end: datetime,
        stripe_subscription_id: str | None,
    ) -> Workspace:
        async with self._db.connect() as conn:
            await conn.execute(
                update(workspaces)
                .where(workspaces.c.id == workspace_id)
                .values(
                    plan=plan.value,
                    seats=entitlement_for(plan).seats,
                    minutes_included=minutes_included,
                    period_start=period_start,
                    period_end=period_end,
                    stripe_subscription_id=stripe_subscription_id,
                )
            )
            row = (await conn.execute(select(workspaces).where(workspaces.c.id == workspace_id))).first()
        if row is None:
            raise LookupError(f"Workspace {workspace_id} vanished while applying a subscription")
        return self._workspace(row)

    async def ping(self) -> bool:
        return await self._db.ping()

    async def close(self) -> None:
        await self._db.close()
