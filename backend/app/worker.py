from arq.connections import RedisSettings

from .byok import byok_keys
from .config import settings
from .pipeline import run_pipeline
from .runs import run_store
from .video import validate_media_tools


async def startup(ctx: dict) -> None:
    validate_media_tools()
    if not settings.queue_enabled or not settings.object_storage_enabled:
        raise RuntimeError("Worker requires Redis and S3-compatible object storage.")
    await run_store.ping()


async def shutdown(ctx: dict) -> None:
    await run_store.close()
    await byok_keys.close()


async def process_run(
    ctx: dict,
    run_id: str,
    *,
    source_url: str | None = None,
    source_key: str | None = None,
) -> None:
    gemini_api_key = await byok_keys.take(run_id)
    await run_pipeline(
        run_id, source_url=source_url, source_key=source_key, gemini_api_key=gemini_api_key
    )


class WorkerSettings:
    functions = [process_run]
    on_startup = startup
    on_shutdown = shutdown
    # Keep imports and local tooling usable without Redis. startup() still refuses
    # to run a production worker until both Redis and object storage are configured.
    redis_settings = (
        RedisSettings.from_dsn(settings.redis_url)
        if settings.redis_url
        else RedisSettings()
    )
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout_seconds
    max_tries = 2
