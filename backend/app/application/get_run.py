from ..domain.entities import Principal, Run, RunStatus
from ..domain.entitlements import MediaTier
from ..domain.errors import RunNotFoundError
from ..domain.policies import can_access_run, is_run_stale
from ..domain.ports import AccountFreeRunAllowance, FreeRunAllowance, RunRepository
from .billing import ExtraRunBilling
from .free_run_holds import settle_free_run_holds

RUN_ABANDONED_MESSAGE = "Analysis stopped responding and did not finish. Please try again."


class GetRunUseCase:
    """Reads one run, and refuses to report progress that stopped happening.

    A run is only ever moved out of PROCESSING by the process that owns it, so
    when that process dies - OOM, container replacement, a cancelled task - no
    one is left to fail it. It would otherwise poll as `processing` until its
    storage TTL expired, days later. The staleness check is the backstop that
    does not depend on the dying process cooperating.
    """

    def __init__(
        self,
        *,
        runs: RunRepository,
        stale_after_seconds: int,
        long_stale_after_seconds: int | None = None,
        free_runs: FreeRunAllowance | None = None,
        account_free_runs: AccountFreeRunAllowance | None = None,
        extra_runs: ExtraRunBilling | None = None,
    ) -> None:
        self._runs = runs
        # A paid extra run this check fails is never billed.
        self._extra_runs = extra_runs
        # The run's held free run is handed back when this check fails it.
        self._free_runs = free_runs
        self._account_free_runs = account_free_runs
        self._stale_after_seconds = stale_after_seconds
        # A signed-in + BYOK run runs under the longer worker timeout, and its
        # FFmpeg step alone can go minutes without a write.
        self._long_stale_after_seconds = max(long_stale_after_seconds or 0, stale_after_seconds)

    def _threshold(self, run: Run) -> int:
        if run.media_tier in (MediaTier.SIGNED_IN_BYOK.value, MediaTier.PAID.value):
            return self._long_stale_after_seconds
        return self._stale_after_seconds

    async def execute(self, run_id: str, principal: Principal) -> Run:
        run = await self._runs.get(run_id)
        if not can_access_run(principal, run):
            raise RunNotFoundError("Run not found.")

        if is_run_stale(run.status, run.updated_at, self._threshold(run)):
            # Persist it so history agrees with what the caller was just told,
            # and so the next reader does not repeat the deduction. A failure
            # to write is not worth failing the read over.
            try:
                failed_it = await self._runs.set_error(run_id, RUN_ABANDONED_MESSAGE)
            except Exception:  # noqa: BLE001
                failed_it = None
            if failed_it is False:
                # The store refused: the worker finished (or failed) the run
                # between our read and this write. Its outcome stands, so
                # report that one rather than a failure nobody recorded.
                fresh = await self._runs.get(run_id)
                if fresh is not None:
                    return fresh
            if failed_it:
                # The person got nothing, so a free run this run took goes
                # back. Exactly once: only the first release of a run acts,
                # and the worker that later drops this job releases again.
                await settle_free_run_holds(
                    run_id,
                    refund=True,
                    free_runs=self._free_runs,
                    account_free_runs=self._account_free_runs,
                    reason="stopped responding and was marked failed",
                )
                if self._extra_runs is not None:
                    await self._extra_runs.void(run_id)
            run.status = RunStatus.FAILED
            run.error = RUN_ABANDONED_MESSAGE
        return run
