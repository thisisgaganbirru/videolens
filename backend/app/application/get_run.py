from ..domain.entities import Principal, Run
from ..domain.errors import RunNotFoundError
from ..domain.ports import RunRepository


class GetRunUseCase:
    def __init__(self, *, runs: RunRepository) -> None:
        self._runs = runs

    async def execute(self, run_id: str, principal: Principal) -> Run:
        run = await self._runs.get(run_id)
        if run is None or run.owner_id != principal.subject:
            raise RunNotFoundError("Run not found.")
        return run
