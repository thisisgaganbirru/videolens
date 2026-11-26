"""The one startup validation both entry points run (docs/backend/startup-checks.md).

The API's lifespan and the worker's `on_startup` call `validate_startup`
with their role, so every rule that applies to a process is checked in that
process: on Railway the two services have their own variables, and a rule
checked only in the API let the worker drift silently (no database, so no
billing, no saved history and no purge, with no error).
"""

import json
import logging

logger = logging.getLogger("videolens")

API = "api"
WORKER = "worker"


async def validate_startup(container, role: str) -> None:
    """Raise RuntimeError (or SchemaOutOfDateError) when this process must
    not start. `role` is API or WORKER."""
    container.media.validate_tools()
    # Creates the directory too, so this replaces the bare `os.makedirs` that
    # used to run at import. That call is what made a bad TEMP_DIR invisible:
    # it succeeded on any string Linux accepts as a directory name.
    container.media.validate_temp_dir()
    settings = container.settings
    if role == API:
        # The device token signs free-run cookies, which only the API issues
        # and reads.
        container.device_tokens.validate_configuration()
    elif not settings.queue_enabled or not container.object_store.enabled:
        raise RuntimeError("Worker requires Redis and S3-compatible object storage.")
    if settings.queue_enabled:
        await container.run_repository.ping()
        if not container.object_store.enabled:
            raise RuntimeError("S3-compatible object storage is required when Redis queueing is enabled.")
        # Refused, not warned: a deployed API with a CORS wildcard is open to
        # every website, a worker on SQLite would keep the extra-run ledger in
        # a local file, and billing without a database would keep
        # subscriptions in one replica's memory. A warning in a platform log
        # reaches nobody.
        error = settings.startup_error(role)
        if error:
            raise RuntimeError(error)
    # Also the database ping: reading the revision is the first query.
    await container.check_schema_use_case.run()
    log_mode(container, role)


def mode_fingerprint(container, role: str) -> dict:
    """What this process runs as, in switches only: never a value or a
    secret. Logged by both services so a difference between their variables
    shows up as two different lines."""
    settings = container.settings
    schema = container.check_schema_use_case.last
    return {
        "role": role,
        "mode": "distributed" if settings.queue_enabled else "local",
        "database": container.database.dialect or "off",
        "schema": schema.state.value if schema is not None else "unchecked",
        "billing": "on" if container.billing_gateway.enabled else "off",
        "auth": "on" if container.jwt_verifier.configured else "off",
        "object_storage": "on" if container.object_store.enabled else "off",
    }


def log_mode(container, role: str) -> None:
    logger.info("Startup mode %s", json.dumps(mode_fingerprint(container, role), sort_keys=True))
