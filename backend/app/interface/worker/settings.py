from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from ...container import container
from ...domain.entitlements import MediaLimits


async def startup(ctx: dict) -> None:
    container.media.validate_tools()
    container.media.validate_temp_dir()
    settings = container.settings
    if not settings.queue_enabled or not container.object_store.enabled:
        raise RuntimeError("Worker requires Redis and S3-compatible object storage.")
    await container.run_repository.ping()


async def shutdown(ctx: dict) -> None:
    await container.run_repository.close()
    await container.key_vault.close()
    await container.free_runs.close()
    await container.long_runs.close()


async def process_run(
    ctx: dict,
    run_id: str,
    *,
    source_url: str | None = None,
    source_key: str | None = None,
    limits: dict | None = None,
) -> None:
    gemini_api_key = await container.key_vault.take(run_id)
    await container.process_run_use_case.execute(
        run_id,
        source_url=source_url,
        source_key=source_key,
        gemini_api_key=gemini_api_key,
        # The limits the API admitted the run under; a job from before they
        # travelled with it (no `limits`) gets the standard ones.
        limits=MediaLimits.from_job_arg(limits),
    )


async def process_long_run(
    ctx: dict,
    run_id: str,
    *,
    source_url: str | None = None,
    source_key: str | None = None,
    limits: dict | None = None,
) -> None:
    """The same job for a run admitted under the signed-in + BYOK limits,
    registered with WORKER_LONG_JOB_TIMEOUT_SECONDS instead of the standard
    timeout (docs/backend/job-queue.md)."""
    await process_run(ctx, run_id, source_url=source_url, source_key=source_key, limits=limits)


async def flush_extra_runs(ctx: dict) -> None:
    """Paid extra runs that completed but whose Stripe meter event did not
    go through (Stripe down, a worker killed in between) are reported here,
    each at most once (docs/backend/billing.md). A no-op with billing off."""
    if container.extra_run_billing.enabled:
        await container.extra_run_billing.flush_due()


class WorkerSettings:
    functions = [
        process_run,
        func(process_long_run, name="process_long_run", timeout=container.settings.long_job_timeout_seconds),
    ]
    # Every 10 minutes; one worker runs each tick (arq's cron lock).
    cron_jobs = [cron(flush_extra_runs, minute=set(range(0, 60, 10)), run_at_startup=False)]
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
