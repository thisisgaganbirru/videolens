import asyncio

from arq import create_pool
from arq.connections import RedisSettings

from .config import settings
from .pipeline import run_pipeline

_pool = None
_local_limit = asyncio.Semaphore(settings.worker_max_jobs)


async def enqueue_run(
    run_id: str,
    *,
    saved_path: str | None = None,
    run_dir: str | None = None,
    source_url: str | None = None,
    source_key: str | None = None,
) -> None:
    global _pool
    if settings.queue_enabled:
        if _pool is None:
            _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await _pool.enqueue_job(
            "process_run",
            run_id,
            source_url=source_url,
            source_key=source_key,
            _job_id=run_id,
        )
        return

    async def run_locally() -> None:
        async with _local_limit:
            await run_pipeline(
                run_id,
                saved_path=saved_path,
                run_dir=run_dir,
                source_url=source_url,
            )

    asyncio.create_task(run_locally())


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
