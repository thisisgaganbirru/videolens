import asyncio
from typing import Awaitable, Callable

from arq import create_pool
from arq.connections import RedisSettings

from ...domain.ports import KeyVault
from ..config import Settings

LocalRunner = Callable[..., Awaitable[None]]


class RunQueue:
    """JobQueue adapter: dispatches to arq/Redis when a queue is configured
    (distributed mode), or runs the job in-process otherwise (local dev).

    `local_runner` is the bound `ProcessRunUseCase.execute` - injected
    rather than imported, so this module never reaches into the
    application layer directly.
    """

    def __init__(self, settings: Settings, local_runner: LocalRunner, key_vault: KeyVault) -> None:
        self._settings = settings
        self._local_runner = local_runner
        self._key_vault = key_vault
        self._pool = None
        self._local_limit = asyncio.Semaphore(settings.worker_max_jobs)

    async def enqueue(
        self,
        run_id: str,
        *,
        saved_path: str | None = None,
        run_dir: str | None = None,
        source_url: str | None = None,
        source_key: str | None = None,
        gemini_api_key: str | None = None,
    ) -> None:
        if self._settings.queue_enabled:
            if self._pool is None:
                self._pool = await create_pool(RedisSettings.from_dsn(self._settings.redis_url))
            if gemini_api_key:
                # Deliberately not passed as a job kwarg - see infrastructure/byok/key_vault.py.
                await self._key_vault.store(run_id, gemini_api_key)
            await self._pool.enqueue_job(
                "process_run",
                run_id,
                source_url=source_url,
                source_key=source_key,
                _job_id=run_id,
            )
            return

        async def run_locally() -> None:
            async with self._local_limit:
                await self._local_runner(
                    run_id,
                    saved_path=saved_path,
                    run_dir=run_dir,
                    source_url=source_url,
                    gemini_api_key=gemini_api_key,
                )

        asyncio.create_task(run_locally())

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
