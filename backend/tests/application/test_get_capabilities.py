import unittest

from app.application.get_capabilities import GetCapabilitiesUseCase
from app.domain.entities import Capability, CapabilityState


class FakeProbe:
    def __init__(self, name: str, state: CapabilityState, *, error: Exception | None = None) -> None:
        self._name = name
        self._state = state
        self._error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def check(self) -> Capability:
        self.calls += 1
        if self._error:
            raise self._error
        return Capability(name=self._name, state=self._state, detail="d", probed=True)


def _use_case(probes, **kwargs) -> GetCapabilitiesUseCase:
    options = {"mode": "local", "cache_seconds": 0.0}
    options.update(kwargs)
    return GetCapabilitiesUseCase(probes=probes, **options)


class GetCapabilitiesUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_every_probe_in_declaration_order(self) -> None:
        use_case = _use_case(
            [
                FakeProbe("media_tools", CapabilityState.OK),
                FakeProbe("run_store", CapabilityState.OK),
            ]
        )

        report = await use_case.execute()

        self.assertEqual([c.name for c in report.capabilities], ["media_tools", "run_store"])
        self.assertEqual(report.mode, "local")
        self.assertEqual(report.state, CapabilityState.OK)

    async def test_overall_state_is_the_worst_reported_state(self) -> None:
        use_case = _use_case(
            [
                FakeProbe("a", CapabilityState.OK),
                FakeProbe("b", CapabilityState.DEGRADED),
                FakeProbe("c", CapabilityState.UNAVAILABLE),
            ]
        )

        report = await use_case.execute()

        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)

    async def test_degraded_wins_over_ok(self) -> None:
        use_case = _use_case(
            [FakeProbe("a", CapabilityState.OK), FakeProbe("b", CapabilityState.DEGRADED)]
        )

        self.assertEqual((await use_case.execute()).state, CapabilityState.DEGRADED)

    async def test_disabled_capabilities_do_not_drag_the_report_down(self) -> None:
        # Object storage being unconfigured in local mode is a deployment
        # shape, not a fault.
        use_case = _use_case(
            [
                FakeProbe("a", CapabilityState.OK),
                FakeProbe("object_storage", CapabilityState.DISABLED),
            ]
        )

        self.assertEqual((await use_case.execute()).state, CapabilityState.OK)

    async def test_a_probe_that_raises_becomes_unavailable_instead_of_failing_the_report(
        self,
    ) -> None:
        use_case = _use_case(
            [
                FakeProbe("ok_one", CapabilityState.OK),
                FakeProbe("broken", CapabilityState.OK, error=RuntimeError("redis://user:pw@host")),
            ]
        )

        report = await use_case.execute()

        broken = next(c for c in report.capabilities if c.name == "broken")
        self.assertEqual(broken.state, CapabilityState.UNAVAILABLE)
        self.assertEqual(report.state, CapabilityState.UNAVAILABLE)
        # The other probe still reported.
        self.assertEqual(len(report.capabilities), 2)

    async def test_a_failing_probe_never_leaks_its_exception_text(self) -> None:
        secret = "redis://user:hunter2@internal-host:6379"
        use_case = _use_case([FakeProbe("broken", CapabilityState.OK, error=RuntimeError(secret))])

        report = await use_case.execute()

        self.assertNotIn("hunter2", report.capabilities[0].detail)
        self.assertNotIn("internal-host", report.capabilities[0].detail)

    async def test_results_are_cached_for_the_cache_window(self) -> None:
        probe = FakeProbe("media_tools", CapabilityState.OK)
        use_case = _use_case([probe], cache_seconds=60.0)

        await use_case.execute()
        await use_case.execute()
        await use_case.execute()

        # The probes shell out and open sockets; an uncached public endpoint
        # would let any caller spawn subprocesses at will.
        self.assertEqual(probe.calls, 1)

    async def test_probes_run_again_once_the_cache_window_passes(self) -> None:
        probe = FakeProbe("media_tools", CapabilityState.OK)
        use_case = _use_case([probe], cache_seconds=0.0)

        await use_case.execute()
        await use_case.execute()

        self.assertEqual(probe.calls, 2)


if __name__ == "__main__":
    unittest.main()


class SerializationTests(unittest.IsolatedAsyncioTestCase):
    """The report is served unauthenticated, so the operator half must never
    reach the wire. This is the invariant, tested at the boundary that
    actually enforces it rather than on any one probe."""

    async def test_log_detail_never_appears_in_the_serialized_report(self) -> None:
        class LeakyProbe(FakeProbe):
            async def check(self) -> Capability:
                return Capability(
                    name=self._name,
                    state=CapabilityState.OK,
                    detail="Media processing is available.",
                    probed=True,
                    log_detail="ffmpeg 8.1.1; 200 shared runs remaining; redis reachable",
                )

        report = await _use_case([LeakyProbe("media_tools", CapabilityState.OK)]).execute()
        wire = report.model_dump_json()

        self.assertNotIn("log_detail", wire)
        self.assertNotIn("8.1.1", wire)
        self.assertNotIn("200 shared runs", wire)
        # The operator half is still reachable in-process, for the log line.
        self.assertIn("ffmpeg 8.1.1", report.capabilities[0].log_detail)
