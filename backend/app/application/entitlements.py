"""Turns "who is calling" into "what are they allowed to do".

One plan in auth phase 1, so every caller gets the same answer: the
deployment's own limits. The seam is kept so the subscription work replaces
the numbers (and reads the workspace's plan here), not the structure.
"""

from ..domain.entities import Principal
from ..domain.entitlements import Entitlement, Plan, entitlement_for


class EntitlementResolver:
    def __init__(self, *, max_duration_seconds: int, max_file_size_mb: int) -> None:
        self._max_duration_seconds = max_duration_seconds
        self._max_file_size_mb = max_file_size_mb

    async def for_principal(self, principal: Principal) -> Entitlement:
        return entitlement_for(
            Plan.FREE,
            max_duration_seconds=self._max_duration_seconds,
            max_file_size_mb=self._max_file_size_mb,
        )
