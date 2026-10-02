"""Turns "who is calling" into "what are they allowed to do".

The plan table lives in the domain; this is the one place that combines it
with the deployment's own default (the anonymous duration cap in `Settings`)
and with a workspace's negotiated override. Every use case that needs a
limit asks here, so a limit is computed one way.
"""

from datetime import datetime, timezone
from decimal import Decimal

from ..domain.entities import Principal, UsageSummary, Workspace
from ..domain.entitlements import Entitlement, Plan, entitlement_for
from ..domain.ports import AccountDirectory, UsageMeter


class EntitlementResolver:
    def __init__(
        self,
        *,
        accounts: AccountDirectory,
        usage: UsageMeter,
        default_max_duration_seconds: int,
    ) -> None:
        self._accounts = accounts
        self._usage = usage
        self._default_max_duration_seconds = default_max_duration_seconds

    async def workspace_for(self, principal: Principal) -> Workspace | None:
        if not principal.workspace_id or not self._accounts.enabled:
            return None
        return await self._accounts.get_workspace(principal.workspace_id)

    def for_workspace(self, workspace: Workspace | None, plan: Plan = Plan.FREE) -> Entitlement:
        entitlement = entitlement_for(workspace.plan if workspace else plan)
        if entitlement.plan is Plan.FREE:
            # The free cap is the deployment's cap: `MAX_DURATION_SECONDS` was
            # the only limit before plans existed and stays the operator's
            # knob for anonymous and free use.
            entitlement = entitlement.with_max_duration(self._default_max_duration_seconds)
        if workspace is not None:
            entitlement = entitlement.with_max_duration(workspace.max_duration_seconds)
        return entitlement

    async def for_principal(self, principal: Principal) -> Entitlement:
        return self.for_workspace(await self.workspace_for(principal), principal.plan)

    async def minutes_used(self, workspace: Workspace) -> Decimal:
        return await self._usage.minutes_used(workspace.workspace_id, workspace.period_start)

    async def usage_summary(self, principal: Principal) -> UsageSummary:
        workspace = await self.workspace_for(principal)
        entitlement = self.for_workspace(workspace, principal.plan)
        now = datetime.now(timezone.utc)
        if workspace is None:
            return UsageSummary(
                plan=entitlement.plan,
                minutes_included=0,
                minutes_used=Decimal("0"),
                period_start=now,
                period_end=now,
                max_duration_seconds=entitlement.max_duration_seconds,
                overage_usd_per_minute=entitlement.overage_usd_per_minute,
            )
        return UsageSummary(
            plan=entitlement.plan,
            minutes_included=workspace.minutes_included or entitlement.minutes_included,
            minutes_used=await self.minutes_used(workspace),
            period_start=workspace.period_start,
            period_end=workspace.period_end,
            max_duration_seconds=entitlement.max_duration_seconds,
            overage_usd_per_minute=entitlement.overage_usd_per_minute,
        )
