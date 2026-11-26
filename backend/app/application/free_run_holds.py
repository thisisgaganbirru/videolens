import logging

from ..domain.ports import AccountFreeRunAllowance, FreeRunAllowance, SpendCap

logger = logging.getLogger("videolens")


async def settle_free_run_holds(
    run_id: str,
    *,
    refund: bool,
    free_runs: FreeRunAllowance | None,
    account_free_runs: AccountFreeRunAllowance | None,
    reason: str,
) -> None:
    """Hand a run's held free run back (`refund`) or just forget it.

    A run holds at most one of the two (device or account free run);
    releasing both is safe, since the one with no hold is a no-op. Every
    allowance acts on the first release for a run only, so two callers (the
    worker and the stale-run sweep) can never refund the same run twice.
    Bookkeeping only: a failure here never touches the run's own outcome,
    and an unreleased hold expires on its own.
    """
    allowances = []
    if free_runs is not None:
        allowances.append(("free run", free_runs))
    if account_free_runs is not None:
        allowances.append(("account free run", account_free_runs))
    for label, allowance in allowances:
        try:
            if await allowance.release(run_id, refund=refund):
                logger.info("Run %s %s, so its %s was handed back", run_id, reason, label)
        except Exception:
            logger.exception("Could not settle the %s for run %s", label, run_id)


async def settle_spend_hold(run_id: str, *, refund: bool, spend_cap: SpendCap | None, reason: str) -> None:
    """Hand a run's held daily-cap unit back (`refund`) or just forget it.
    Same contract as the free run: only the first release of a run acts, a
    run that took no unit (own key, paid, cap off) holds nothing, and a
    failure here is bookkeeping only (the hold expires on its own)."""
    if spend_cap is None:
        return
    try:
        if await spend_cap.release(run_id, refund=refund):
            logger.info("Run %s %s, so its daily cap unit was handed back", run_id, reason)
    except Exception:
        logger.exception("Could not settle the daily cap unit for run %s", run_id)
