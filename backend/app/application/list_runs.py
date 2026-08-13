from ..domain.entities import Principal, Run
from ..domain.ports import RunRepository


class ListRunsUseCase:
    def __init__(self, *, runs: RunRepository) -> None:
        self._runs = runs

    async def execute(self, principal: Principal) -> list[Run]:
        return await self._runs.list_for_owner(principal.subject)
