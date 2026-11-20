import asyncio

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from ...container import container
from ...domain.entitlements import MediaLimits
from ..startup import WORKER, validate_startup


async def startup(ctx: dict) -> None:
    # First, so the checks below and every `videolens` line after them come
    # out in the API's JSON format (arq installs a handler on `arq` only).
    container.configure_worker_logging()
    await validate_startup(container, WORKER)


async def shutdown(ctx: dict) -> None:
    # Everything the container opened, the SQL engine included; arq calls
    # this once, from `Worker.close`.
    await container.close()


async def process_run(
    ctx: dict,
    run_id: str,
    *,
    source_url: str | None = None,
    source_key: str | None = None,
    limits: dict | None = None,
) -> None:
    await _run_job(
        run_id,
        timeout_seconds=container.settings.worker_job_timeout_seconds,
        source_url=source_url,
        source_key=source_key,
        limits=limits,
    )


async def _run_job(
    run_id: str,
    *,
    timeout_seconds: float,
    source_url: str | None,
    source_key: str | None,
    limits: dict | None,
) -> None:
    # When arq's `job_timeout` will cancel this job. Taken first, so it is
    # never later than arq's own clock: a cancellation before it is a
    # shutdown (the run is left for arq's retry), at or after it a timeout.
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    gemini_api_key = await container.key_vault.take(run_id)
    await container.process_run_use_case.execute(
        run_id,
        source_url=source_url,
        source_key=source_key,
        gemini_api_key=gemini_api_key,
        # The limits the API admitted the run under; a job from before they
        # travelled with it (no `limits`) gets the standard ones.
        limits=MediaLimits.from_job_arg(limits),
        deadline=deadline,
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
    await _run_job(
        run_id,
        timeout_seconds=container.settings.long_job_timeout_seconds,
        source_url=source_url,
        source_key=source_key,
        limits=limits,
    )


async def flush_extra_runs(ctx: dict) -> None:
    """Paid extra runs that completed but whose Stripe meter event did not
    go through (Stripe down, a worker killed in between) are reported here,
    each at most once (docs/backend/billing.md). First the held ones are
    reconciled with their run's stored outcome (completed -> due, failed or
    gone -> void) and due ones too old to report are voided with a warning.
    A no-op with billing off."""
    if container.extra_run_billing.enabled:
        await container.extra_run_billing.reconcile()
        await container.extra_run_billing.flush_due()


async def account_cleanup(ctx: dict) -> None:
    """Hourly: accounts past their 30-day deletion hold are removed for good
    (Supabase user, then every row), and saved runs past their post-cancel
    window are removed (docs/backend/saved-history.md). Bounded per tick and
    idempotent; a no-op without a database."""
    await container.account_cleanup_use_case.run()


class WorkerSettings:
    functions = [
        process_run,
        func(process_long_run, name="process_long_run", timeout=container.settings.long_job_timeout_seconds),
    ]
    # Every 10 minutes; one worker runs each tick (arq's cron lock).
    cron_jobs = [
        cron(flush_extra_runs, minute=set(range(0, 60, 10)), run_at_startup=False),
        cron(account_cleanup, minute={25}, run_at_startup=False),
    ]
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
    # On SIGTERM: stop taking jobs and let running ones finish for this long,
    # then cancel what is left (re-queued; the run resumes on the next
    # worker). Must stay under the platform's stop grace period.
    job_completion_wait = container.settings.worker_job_completion_wait_seconds
    # The first try, plus one after a shutdown cancelled it. A timeout is
    # final (arq does not retry it), and so is any failure process_run records.
    max_tries = 2
