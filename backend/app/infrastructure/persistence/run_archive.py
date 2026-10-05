"""RunArchive adapter over Postgres (SQLite in tests): a workspace's finished
runs, kept past the live store's TTL and searchable."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, cast, delete, func, insert, literal, or_, select, update

from ...domain.entities import (
    AnalysisCompleteness,
    Run,
    RunStatus,
    ScreenTextSegment,
    SourceMetadata,
    TokenUsage,
    TranscriptSegment,
    VideoAnalysis,
)
from ...domain.entitlements import Plan
from .database import Database, as_utc, utcnow
from .schema import run_results, runs


class PostgresRunArchive:
    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def enabled(self) -> bool:
        return self._db.enabled

    @staticmethod
    def _row_from_run(run: Run) -> dict:
        return dict(
            id=run.run_id,
            owner_id=run.owner_id,
            workspace_id=run.workspace_id,
            plan=run.plan.value,
            status=run.status.value,
            stage=run.stage,
            source_url=run.source_url or (run.source_metadata.source_url if run.source_metadata else None),
            platform=run.source_metadata.platform.lower() if run.source_metadata else None,
            title=run.result.title if run.result else (run.source_metadata.title if run.source_metadata else None),
            duration_seconds=run.duration_seconds,
            max_duration_seconds=run.max_duration_seconds,
            completeness=run.completeness.value,
            error=run.error,
            input_tokens=run.usage.input_tokens if run.usage else None,
            output_tokens=run.usage.output_tokens if run.usage else None,
            created_at=run.created_at,
            updated_at=run.updated_at,
            completed_at=utcnow() if run.status in (RunStatus.COMPLETE, RunStatus.FAILED) else None,
        )

    @staticmethod
    def _result_row(run: Run) -> dict | None:
        if run.result is None:
            return None
        result = run.result
        return dict(
            run_id=run.run_id,
            summary=result.summary,
            transcript=result.transcript,
            screen_text=result.screen_text,
            markdown=result.markdown,
            transcript_segments=[segment.model_dump() for segment in result.transcript_segments],
            screen_text_segments=[segment.model_dump() for segment in result.screen_text_segments],
            source_metadata=run.source_metadata.model_dump() if run.source_metadata else None,
        )

    @staticmethod
    def _run_from_rows(row, result_row) -> Run:
        result = None
        if result_row is not None:
            result = VideoAnalysis(
                title=row.title or "",
                summary=result_row.summary,
                transcript=result_row.transcript,
                transcript_segments=[TranscriptSegment(**s) for s in (result_row.transcript_segments or [])],
                screen_text=result_row.screen_text,
                screen_text_segments=[ScreenTextSegment(**s) for s in (result_row.screen_text_segments or [])],
                markdown=result_row.markdown,
            )
        metadata = (
            SourceMetadata(**result_row.source_metadata)
            if result_row is not None and result_row.source_metadata
            else None
        )
        usage = (
            TokenUsage(input_tokens=row.input_tokens or 0, output_tokens=row.output_tokens or 0)
            if row.input_tokens is not None or row.output_tokens is not None
            else None
        )
        return Run(
            run_id=row.id,
            owner_id=row.owner_id,
            status=RunStatus(row.status),
            created_at=as_utc(row.created_at),
            updated_at=as_utc(row.updated_at),
            stage=row.stage,
            result=result,
            error=row.error,
            source_metadata=metadata,
            completeness=AnalysisCompleteness(row.completeness),
            workspace_id=row.workspace_id,
            plan=Plan(row.plan),
            max_duration_seconds=row.max_duration_seconds,
            source_url=row.source_url,
            duration_seconds=row.duration_seconds,
            usage=usage,
        )

    async def archive(self, run: Run) -> None:
        if not self.enabled:
            return
        row = self._row_from_run(run)
        result_row = self._result_row(run)
        async with self._db.connect() as conn:
            exists = await conn.scalar(select(runs.c.id).where(runs.c.id == run.run_id))
            if exists:
                values = {k: v for k, v in row.items() if k != "id"}
                await conn.execute(update(runs).where(runs.c.id == run.run_id).values(**values))
            else:
                await conn.execute(insert(runs).values(**row))
            if result_row is not None:
                await conn.execute(delete(run_results).where(run_results.c.run_id == run.run_id))
                await conn.execute(insert(run_results).values(**result_row))

    async def get(self, run_id: str) -> Optional[Run]:
        if not self.enabled:
            return None
        async with self._db.connect() as conn:
            row = (await conn.execute(select(runs).where(runs.c.id == run_id))).first()
            if row is None:
                return None
            result_row = (
                await conn.execute(select(run_results).where(run_results.c.run_id == run_id))
            ).first()
        return self._run_from_rows(row, result_row)

    async def _fetch(self, conn, statement) -> list[Run]:
        rows = (await conn.execute(statement)).all()
        if not rows:
            return []
        ids = [row.id for row in rows]
        results = {
            r.run_id: r
            for r in (await conn.execute(select(run_results).where(run_results.c.run_id.in_(ids)))).all()
        }
        return [self._run_from_rows(row, results.get(row.id)) for row in rows]

    async def list_for_owner(self, owner_id: str, limit: int = 20) -> list[Run]:
        if not self.enabled:
            return []
        statement = (
            select(runs)
            .where(runs.c.owner_id == owner_id)
            .order_by(runs.c.created_at.desc())
            .limit(limit)
        )
        async with self._db.connect() as conn:
            return await self._fetch(conn, statement)

    async def search(
        self,
        owner_id: str,
        *,
        query: str = "",
        platform: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Run]:
        if not self.enabled:
            return []
        statement = (
            select(runs)
            .outerjoin(run_results, run_results.c.run_id == runs.c.id)
            .where(runs.c.owner_id == owner_id)
        )
        if platform:
            statement = statement.where(runs.c.platform == platform.lower())
        if since is not None:
            statement = statement.where(runs.c.created_at >= since)
        if until is not None:
            statement = statement.where(runs.c.created_at <= until)
        if query:
            document = func.concat_ws(
                literal(" "),
                func.coalesce(runs.c.title, ""),
                func.coalesce(run_results.c.summary, ""),
                func.coalesce(run_results.c.screen_text, ""),
                func.coalesce(run_results.c.transcript, ""),
            )
            if self._db.dialect == "postgresql":
                # Matches the expression the GIN index in the migration is
                # built over, so this is an index scan, not a table scan.
                statement = statement.where(
                    func.to_tsvector(literal("english"), document).op("@@")(
                        func.plainto_tsquery(literal("english"), query)
                    )
                )
            else:
                pattern = f"%{query.lower()}%"
                statement = statement.where(
                    or_(
                        func.lower(func.coalesce(runs.c.title, "")).like(pattern),
                        func.lower(func.coalesce(run_results.c.summary, "")).like(pattern),
                        func.lower(func.coalesce(run_results.c.screen_text, "")).like(pattern),
                        func.lower(func.coalesce(run_results.c.transcript, "")).like(pattern),
                    )
                )
        statement = statement.order_by(runs.c.created_at.desc()).limit(limit).offset(offset)
        async with self._db.connect() as conn:
            return await self._fetch(conn, statement)

    async def ping(self) -> bool:
        return await self._db.ping()

    async def close(self) -> None:
        await self._db.close()
