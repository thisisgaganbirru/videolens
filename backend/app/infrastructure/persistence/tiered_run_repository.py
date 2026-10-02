"""RunRepository that reads the live store first and the archive second.

The live store (Redis, or a dict in local mode) is where a run is born and
where every progress write lands: it is fast, it expires, and it is all an
anonymous caller ever has. The archive is Postgres: a workspace's finished
runs are copied there the moment they complete or fail, and read from there
once Redis has forgotten them. Anonymous runs never reach the archive, which
is what keeps free use client-side-only as the product direction requires.
"""

from typing import Optional

from ...domain.entities import (
    AnalysisCompleteness,
    Run,
    RunStatus,
    SourceMetadata,
    TokenUsage,
    VideoAnalysis,
)
from ...domain.entitlements import Plan
from ...domain.ports import RunArchive, RunRepository


class TieredRunRepository:
    def __init__(self, live: RunRepository, archive: RunArchive) -> None:
        self._live = live
        self._archive = archive

    async def create(
        self,
        run_id: str,
        owner_id: str,
        *,
        workspace_id: str | None = None,
        plan: Plan = Plan.FREE,
        max_duration_seconds: int | None = None,
        source_url: str | None = None,
    ) -> Run:
        return await self._live.create(
            run_id,
            owner_id,
            workspace_id=workspace_id,
            plan=plan,
            max_duration_seconds=max_duration_seconds,
            source_url=source_url,
        )

    async def get(self, run_id: str) -> Optional[Run]:
        run = await self._live.get(run_id)
        if run is not None or not self._archive.enabled:
            return run
        return await self._archive.get(run_id)

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        live = await self._live.list_for_owner(owner_id, limit)
        if not self._archive.enabled or not owner_id.startswith("workspace:"):
            return live
        archived = await self._archive.list_for_owner(owner_id, limit)
        seen = {run.run_id for run in live}
        merged = live + [run for run in archived if run.run_id not in seen]
        merged.sort(key=lambda run: run.created_at, reverse=True)
        return merged[:limit]

    async def _archive_if_owned(self, run_id: str) -> None:
        if not self._archive.enabled:
            return
        run = await self._live.get(run_id)
        if run is not None and run.workspace_id:
            await self._archive.archive(run)

    async def set_status(self, run_id: str, status: RunStatus) -> None:
        await self._live.set_status(run_id, status)

    async def set_stage(self, run_id: str, stage: str) -> None:
        await self._live.set_stage(run_id, stage)

    async def set_result(
        self,
        run_id: str,
        result: VideoAnalysis,
        completeness: AnalysisCompleteness = AnalysisCompleteness.FULL,
    ) -> None:
        await self._live.set_result(run_id, result, completeness)
        await self._archive_if_owned(run_id)

    async def set_source_metadata(self, run_id: str, metadata: SourceMetadata) -> None:
        await self._live.set_source_metadata(run_id, metadata)

    async def set_error(self, run_id: str, error: str) -> None:
        await self._live.set_error(run_id, error)
        await self._archive_if_owned(run_id)

    async def set_duration(self, run_id: str, duration_seconds: float) -> None:
        await self._live.set_duration(run_id, duration_seconds)

    async def set_usage(self, run_id: str, usage: TokenUsage) -> None:
        await self._live.set_usage(run_id, usage)
        # Usage arrives after the result is stored in the engine's callback
        # order only by accident of implementation; re-archive so the copy of
        # record carries the token counts whichever lands last.
        await self._archive_if_owned(run_id)

    async def ping(self) -> bool:
        return await self._live.ping()

    async def close(self) -> None:
        await self._live.close()
        await self._archive.close()
