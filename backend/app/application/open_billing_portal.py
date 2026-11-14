"""`POST /api/billing/portal`: a Stripe Customer Portal URL (card,
invoices, cancel).

A complimentary Plus account with no Stripe customer (or with Stripe off)
gets 409 `complimentary_plan`: there is nothing to manage. One that also
has a Stripe customer (a subscription, live or past) opens the portal as
anyone else does."""

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import (
    BillingNotConfiguredError,
    ComplimentaryPlanError,
    ForbiddenError,
    NoBillingAccountError,
)
from .billing import BillingPlans


class OpenBillingPortalUseCase:
    def __init__(self, *, plans: BillingPlans) -> None:
        self._plans = plans

    async def execute(self, principal: Principal) -> str:
        if principal.method is not AuthMethod.TOKEN:
            raise ForbiddenError("This needs a signed-in session, not an API key.")
        if not self._plans.enabled:
            if await self._plans.is_complimentary(principal.account_id):
                raise ComplimentaryPlanError()
            raise BillingNotConfiguredError()
        account = await self._plans.accounts.get(principal.account_id) if principal.account_id else None
        if account is None:
            if await self._plans.is_complimentary(principal.account_id):
                raise ComplimentaryPlanError()
            raise NoBillingAccountError()
        return await self._plans.gateway.create_portal_session(account.stripe_customer_id)
