import asyncio
import logging
import time

from ..domain.entities import Capability, CapabilityReport, CapabilityState
from ..domain.ports import CapabilityProbe

logger = logging.getLogger("videolens")

# Worst-first: the overall state is the most severe one any probe reported.
# DISABLED is absent on purpose - a capability nobody configured (object
# storage in local mode) is not a fault, so it never drags the report down.
_SEVERITY = [CapabilityState.UNAVAILABLE, CapabilityState.DEGRADED, CapabilityState.OK]


class GetCapabilitiesUseCase:
    """Reports what the service can actually do right now, one dependency at
    a time.

    Two properties matter more than the field list. First, a probe that raises
    is reported as unavailable rather than crashing the report - a broken
    dependency must not also break the endpoint that exists to describe it.
    Second, results are cached for a few seconds: the probes shell out and
    open sockets, so an unauthenticated endpoint calling them once per request
    would hand any caller a way to spawn subprocesses at will.
    """

    def __init__(
        self,
        *,
        probes: list[CapabilityProbe],
        mode: str,
        cache_seconds: float = 10.0,
    ) -> None:
        self._probes = probes
        self._mode = mode
        self._cache_seconds = cache_seconds
        self._cached: CapabilityReport | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def execute(self) -> CapabilityReport:
        async with self._lock:
            now = time.monotonic()
            if self._cached is not None and now - self._cached_at < self._cache_seconds:
                return self._cached

            results = await asyncio.gather(
                *(probe.check() for probe in self._probes), return_exceptions=True
            )
            capabilities = [
                self._resolve(probe, result) for probe, result in zip(self._probes, results)
            ]
            report = CapabilityReport(
                state=self._overall(capabilities),
                mode=self._mode,
                capabilities=capabilities,
            )
            self._cached = report
            self._cached_at = now
            return report

    def _resolve(self, probe: CapabilityProbe, result: object) -> Capability:
        if isinstance(result, Capability):
            return result
        # Same masking rule as ProcessRunUseCase: the real exception goes to
        # the logs, never into a response an anonymous caller can read.
        logger.error("Capability probe %s failed", probe.name, exc_info=result)
        return Capability(
            name=probe.name,
            state=CapabilityState.UNAVAILABLE,
            detail="The health check for this capability failed. See server logs.",
            probed=True,
        )

    @staticmethod
    def _overall(capabilities: list[Capability]) -> CapabilityState:
        states = {capability.state for capability in capabilities}
        for state in _SEVERITY:
            if state in states:
                return state
        return CapabilityState.OK
