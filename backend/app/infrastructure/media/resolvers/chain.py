import logging

from ....domain.entities import SavedUpload
from ....domain.errors import MediaValidationError
from ....domain.ports import SourceResolver

logger = logging.getLogger("videolens")


class ResolverChain:
    """Tries each resolver that claims a URL, in order, until one returns media.

    The point is that a source has more than one route to it, and the route
    that works changes without warning - a site ships an anti-bot check, an
    extractor goes stale, a CDN starts refusing a client. Encoding the routes
    as an ordered list means recovering from that is a reordering, not a
    rewrite, and adding a new one touches nothing that already works.

    Order matters and is set by the composition root: the first resolver is
    the primary path and the rest are recovery. A resolver is only consulted
    if it says it can handle the URL, so a fallback that is wrong for a link
    is never even attempted.
    """

    def __init__(self, resolvers: list[SourceResolver]) -> None:
        if not resolvers:
            raise ValueError("A resolver chain needs at least one resolver.")
        self._resolvers = resolvers

    async def fetch(self, run_id: str, url: str) -> SavedUpload:
        primary_error: MediaValidationError | None = None
        attempted: list[str] = []

        for resolver in self._resolvers:
            if not resolver.can_handle(url):
                continue
            attempted.append(resolver.name)
            try:
                saved = await resolver.fetch(run_id, url)
            except MediaValidationError as exc:
                logger.info("Resolver %s could not fetch run %s: %s", resolver.name, run_id, exc)
                if primary_error is None:
                    primary_error = exc
                continue
            if len(attempted) > 1:
                logger.info(
                    "Resolver %s recovered run %s after %s failed",
                    resolver.name,
                    run_id,
                    ", ".join(attempted[:-1]),
                )
            return saved

        if primary_error is not None:
            # The first resolver's message is the one that reaches the caller.
            # It is the primary path and carries the curated, actionable
            # diagnostics (the login-cookie guidance, for one); a fallback
            # failing afterwards usually just says "404".
            raise primary_error
        raise MediaValidationError("No downloader could handle this URL.")
