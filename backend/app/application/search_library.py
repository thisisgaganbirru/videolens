"""Search across everything a workspace has analyzed.

With an archive configured this is a real full-text search over the durable
store. Without one there is only the live store's recent history, so the
same request degrades to a title match over that - a smaller answer, never
an error, so the frontend's library tab works on every deployment.
"""

from datetime import datetime

from ..domain.entities import Principal, Run
from ..domain.ports import RunArchive, RunRepository

MAX_LIMIT = 50


class SearchLibraryUseCase:
    def __init__(self, *, runs: RunRepository, archive: RunArchive) -> None:
        self._runs = runs
        self._archive = archive

    async def execute(
        self,
        principal: Principal,
        *,
        query: str = "",
        platform: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Run]:
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        query = query.strip()
        platform = platform.strip().lower() if platform else None
        if self._archive.enabled and principal.workspace_id:
            return await self._archive.search(
                principal.owner_id,
                query=query,
                platform=platform,
                since=since,
                until=until,
                limit=limit,
                offset=offset,
            )

        recent = await self._runs.list_for_owner(principal.owner_id, limit=MAX_LIMIT)
        needle = query.lower()
        matches = []
        for run in recent:
            if since and run.created_at < since:
                continue
            if until and run.created_at > until:
                continue
            if platform and (run.source_metadata is None or run.source_metadata.platform.lower() != platform):
                continue
            if needle:
                haystack = " ".join(
                    part
                    for part in (
                        run.result.title if run.result else "",
                        run.result.summary if run.result else "",
                        run.result.screen_text if run.result else "",
                        run.result.transcript if run.result else "",
                        run.source_metadata.title if run.source_metadata else "",
                    )
                    if part
                ).lower()
                if needle not in haystack:
                    continue
            matches.append(run)
        return matches[offset : offset + limit]
