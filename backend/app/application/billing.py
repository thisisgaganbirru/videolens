"""Subscriptions: starting one, managing one, and applying what the provider
says happened to one. Money-shaped, so every path refuses loudly when the
deployment has no billing provider configured."""

import logging

from ..domain.entities import BillingEventKind, Principal, Workspace, WorkspaceRole
from ..domain.entitlements import Plan, entitlement_for
from ..domain.errors import (
    BillingNotConfiguredError,
    PermissionDeniedError,
    WorkspaceNotFoundError,
)
from ..domain.ports import AccountDirectory, BillingGateway

logger = logging.getLogger("videolens")


async def _owned_workspace(accounts: AccountDirectory, principal: Principal) -> Workspace:
    if not accounts.enabled or not principal.workspace_id or not principal.account_id:
        raise WorkspaceNotFoundError("Sign in to manage a subscription.")
    workspace = await accounts.get_workspace(principal.workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError("Workspace not found.")
    role = await accounts.member_role(workspace.workspace_id, principal.account_id)
    if role != WorkspaceRole.OWNER.value:
        raise PermissionDeniedError("Only the workspace owner can change its plan.")
    return workspace


class StartCheckoutUseCase:
    def __init__(self, *, accounts: AccountDirectory, billing: BillingGateway) -> None:
        self._accounts = accounts
        self._billing = billing

    async def execute(
        self, principal: Principal, plan: Plan, *, success_url: str, cancel_url: str
    ) -> str:
        if not self._billing.enabled:
            raise BillingNotConfiguredError("Paid plans are not available on this deployment yet.")
        if plan is Plan.FREE:
            raise PermissionDeniedError("The free plan has nothing to check out.")
        workspace = await _owned_workspace(self._accounts, principal)
        return await self._billing.create_checkout_url(
            workspace=workspace,
            plan=plan,
            customer_email=principal.email,
            success_url=success_url,
            cancel_url=cancel_url,
        )


class OpenBillingPortalUseCase:
    def __init__(self, *, accounts: AccountDirectory, billing: BillingGateway) -> None:
        self._accounts = accounts
        self._billing = billing

    async def execute(self, principal: Principal, *, return_url: str) -> str:
        if not self._billing.enabled:
            raise BillingNotConfiguredError("Paid plans are not available on this deployment yet.")
        workspace = await _owned_workspace(self._accounts, principal)
        if not workspace.stripe_customer_id:
            raise PermissionDeniedError("This workspace has no subscription to manage yet.")
        return await self._billing.create_portal_url(
            customer_id=workspace.stripe_customer_id, return_url=return_url
        )


class ApplyBillingEventUseCase:
    """Takes a verified webhook and makes the workspace agree with it.

    Idempotent by construction: every event carries the subscription's whole
    state (plan, period), so applying the same one twice or out of order
    lands on the same row values. Ignored kinds return None and are still a
    200 to the provider - there is nothing to retry.
    """

    def __init__(self, *, accounts: AccountDirectory, billing: BillingGateway) -> None:
        self._accounts = accounts
        self._billing = billing

    async def execute(self, payload: bytes, signature: str) -> Workspace | None:
        event = self._billing.parse_webhook(payload, signature)
        if event.kind is BillingEventKind.IGNORED:
            return None

        workspace = None
        if event.workspace_id:
            workspace = await self._accounts.get_workspace(event.workspace_id)
        if workspace is None and event.customer_id:
            workspace = await self._accounts.get_workspace_by_customer(event.customer_id)
        if workspace is None:
            logger.warning("Billing event %s matched no workspace", event.event_id)
            return None

        if event.customer_id and workspace.stripe_customer_id != event.customer_id:
            await self._accounts.set_customer(workspace.workspace_id, event.customer_id)

        if event.kind is BillingEventKind.SUBSCRIPTION_ENDED:
            plan = Plan.FREE
        else:
            plan = event.plan or workspace.plan
        period_start = event.period_start or workspace.period_start
        period_end = event.period_end or workspace.period_end
        return await self._accounts.apply_subscription(
            workspace.workspace_id,
            plan=plan,
            minutes_included=entitlement_for(plan).minutes_included,
            period_start=period_start,
            period_end=period_end,
            stripe_subscription_id=None
            if event.kind is BillingEventKind.SUBSCRIPTION_ENDED
            else event.subscription_id,
        )
