from ..domain.entities import Principal, Run, RunStatus
from ..domain.errors import RunNotFoundError
from ..domain.policies import is_run_stale
from ..domain.ports import RunRepository

RUN_ABANDONED_MESSAGE = "Analysis stopped responding and did not finish. Please try again."


class GetRunUseCase:
    """Reads one run, and refuses to report progress that stopped happening.

    A run is only ever moved out of PROCESSING by the process that owns it, so
    when that process dies - OOM, container replacement, a cancelled task - no
    one is left to fail it. It would otherwise poll as `processing` until its
    storage TTL expired, days later. The staleness check is the backstop that
    does not depend on the dying process cooperating.
    """

    def __init__(self, *, runs: RunRepository, stale_after_seconds: int) -> None:
        self._runs = runs
        self._stale_after_seconds = stale_after_seconds

    async def execute(self, run_id: str, principal: Principal) -> Run:
        run = await self._runs.get(run_id)
        if run is None or run.owner_id != principal.subject:
            raise RunNotFoundError("Run not found.")

        if is_run_stale(run.status, run.updated_at, self._stale_after_seconds):
            # Persist it so history agrees with what the caller was just told,
            # and so the next reader does not repeat the deduction. A failure
            # to write is not worth failing the read over.
            try:
                await self._runs.set_error(run_id, RUN_ABANDONED_MESSAGE)
            except Exception:  # noqa: BLE001
                pass
            run.status = RunStatus.FAILED
            run.error = RUN_ABANDONED_MESSAGE
        return run
