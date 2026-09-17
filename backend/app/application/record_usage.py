"""Writes the one record billing is built on: how many minutes of media a
workspace's run consumed, and what it cost us."""

import logging
import uuid
from datetime import datetime, timezone

from ..domain.entities import TokenUsage, UsageEvent
from ..domain.entitlements import MediaResolution, billable_minutes, estimate_cost_usd
from ..domain.ports import AccountDirectory, BillingGateway, UsageMeter

logger = logging.getLogger("videolens")


class RecordUsageUseCase:
    def __init__(
        self,
        *,
        usage: UsageMeter,
        accounts: AccountDirectory,
        billing: BillingGateway,
    ) -> None:
        self._usage = usage
        self._accounts = accounts
        self._billing = billing

    async def execute(
        self,
        *,
        run_id: str,
        workspace_id: str,
        duration_seconds: float,
        resolution: MediaResolution,
        tokens: TokenUsage | None,
    ) -> UsageEvent:
        minutes = billable_minutes(duration_seconds)
        event = UsageEvent(
            event_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            run_id=run_id,
            minutes_billed=minutes,
            input_tokens=tokens.input_tokens if tokens else 0,
            output_tokens=tokens.output_tokens if tokens else 0,
            cost_estimate_usd=estimate_cost_usd(duration_seconds, resolution),
            created_at=datetime.now(timezone.utc),
        )
        # Report to the billing provider's meter before persisting so the
        # meter event id lands on the same row. A meter failure must not lose
        # the local record - the local one is what the plan cap reads.
        workspace = await self._accounts.get_workspace(workspace_id)
        if self._billing.enabled and workspace is not None and workspace.stripe_customer_id:
            try:
                event.meter_event_id = await self._billing.report_usage(
                    customer_id=workspace.stripe_customer_id, minutes=minutes, run_id=run_id
                )
            except Exception:  # noqa: BLE001 - metering never fails a finished run
                logger.exception("Usage for run %s was not reported to the billing meter", run_id)
        await self._usage.record(event)
        return event
