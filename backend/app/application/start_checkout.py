"""`POST /api/billing/checkout`: a hosted Stripe Checkout URL for the plan."""

from ..domain.entities import AuthMethod, Principal
from ..domain.errors import (
    AccountsNotConfiguredError,
    AlreadySubscribedError,
    BillingIntervalError,
    BillingNotConfiguredError,
    ForbiddenError,
)
from ..domain.policies import subscription_is_live
from .billing import BillingPlans

INTERVALS = ("month", "year")


class StartCheckoutUseCase:
    def __init__(self, *, plans: BillingPlans) -> None:
        self._plans = plans

    async def execute(self, principal: Principal, interval: str) -> str:
        if principal.method is not AuthMethod.TOKEN:
            # Defence in depth behind `require_person`: an agent's key must
            # never start a subscription on its owner's card.
            raise ForbiddenError("This needs a signed-in session, not an API key.")
        if not self._plans.enabled:
            raise BillingNotConfiguredError()
        if not principal.account_id:
            raise AccountsNotConfiguredError("Accounts are not available on this server.")
        if interval not in INTERVALS:
            raise BillingIntervalError("Choose monthly or yearly billing.")
        if interval == "year" and not self._plans.gateway.yearly_available:
            raise BillingIntervalError("Yearly billing is not available yet.")
        account = await self._plans.accounts.get(principal.account_id)
        if account is not None and subscription_is_live(account.status):
            raise AlreadySubscribedError()
        if account is None:
            customer_id = await self._plans.gateway.create_customer(principal.account_id, principal.email)
            # A racing checkout may have linked one first; the stored one wins.
            account = await self._plans.accounts.link_customer(principal.account_id, customer_id)
        return await self._plans.gateway.create_checkout_session(
            customer_id=account.stripe_customer_id, account_id=principal.account_id, interval=interval
        )
