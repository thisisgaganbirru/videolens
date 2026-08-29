import asyncio
import logging
import time

from ..domain.entities import ReleaseIndex
from ..domain.ports import ReleaseCatalog

logger = logging.getLogger("videolens")


class GetReleasesUseCase:
    """Serves the app's release index.

    Cached because every client polls it and GitHub's API is rate limited per
    token, not per caller - without a cache one popular page could exhaust the
    budget for everyone. A failed fetch serves the last good answer rather than
    an error: a stale release list is strictly better than a broken Releases
    tab, and an update check that briefly misses a new build simply retries.
    """

    def __init__(self, *, catalog: ReleaseCatalog, cache_seconds: float = 300.0) -> None:
        self._catalog = catalog
        self._cache_seconds = cache_seconds
        self._cached: ReleaseIndex | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def execute(self) -> ReleaseIndex:
        async with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached_at < self._cache_seconds:
                return self._cached
            try:
                index = await self._catalog.fetch()
            except Exception:
                logger.exception("Could not refresh the release index")
                if self._cached is not None:
                    return self._cached
                return ReleaseIndex(releases=[])
            self._cached = index
            self._cached_at = now
            return index
