"""UsageMeter adapter: the ledger of billed minutes per workspace."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, insert, select

from ...domain.entities import UsageEvent
from .database import Database
from .schema import usage_events


class PostgresUsageMeter:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def minutes_used(self, workspace_id: str, since: datetime) -> Decimal:
        if not self._db.enabled:
            return Decimal("0")
        async with self._db.connect() as conn:
            total = await conn.scalar(
                select(func.coalesce(func.sum(usage_events.c.minutes_billed), 0)).where(
                    usage_events.c.workspace_id == workspace_id,
                    usage_events.c.created_at >= since,
                )
            )
        return Decimal(str(total or 0))

    async def record(self, event: UsageEvent) -> None:
        if not self._db.enabled:
            return
        async with self._db.connect() as conn:
            # One event per run: a retried job must not bill twice.
            existing = await conn.scalar(select(usage_events.c.id).where(usage_events.c.run_id == event.run_id))
            if existing:
                return
            await conn.execute(
                insert(usage_events).values(
                    id=event.event_id,
                    workspace_id=event.workspace_id,
                    run_id=event.run_id,
                    minutes_billed=event.minutes_billed,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cost_estimate_usd=event.cost_estimate_usd,
                    meter_event_id=event.meter_event_id,
                    created_at=event.created_at,
                )
            )

    async def close(self) -> None:
        await self._db.close()
