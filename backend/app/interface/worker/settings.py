from arq.connections import RedisSettings

from ...container import container


async def startup(ctx: dict) -> None:
    container.media.validate_tools()
    settings = container.settings
    if not settings.queue_enabled or not container.object_store.enabled:
        raise RuntimeError("Worker requires Redis and S3-compatible object storage.")
    await container.run_repository.ping()


async def shutdown(ctx: dict) -> None:
    await container.run_repository.close()
    await container.key_vault.close()


async def process_run(
    ctx: dict,
    run_id: str,
    *,
    source_url: str | None = None,
    source_key: str | None = None,
) -> None:
    gemini_api_key = await container.key_vault.take(run_id)
    await container.process_run_use_case.execute(
        run_id, source_url=source_url, source_key=source_key, gemini_api_key=gemini_api_key
    )


class WorkerSettings:
    functions = [process_run]
    on_startup = startup
    on_shutdown = shutdown
    # Keep imports and local tooling usable without Redis. startup() still refuses
    # to run a production worker until both Redis and object storage are configured.
    redis_settings = (
        RedisSettings.from_dsn(container.settings.redis_url)
        if container.settings.redis_url
        else RedisSettings()
    )
    max_jobs = container.settings.worker_max_jobs
    job_timeout = container.settings.worker_job_timeout_seconds
    max_tries = 2
