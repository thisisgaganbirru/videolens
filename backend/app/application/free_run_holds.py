import logging

from ..domain.ports import AccountFreeRunAllowance, FreeRunAllowance

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
