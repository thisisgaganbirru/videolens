from ..domain.entities import FreeRunStatus
from ..domain.ports import DeviceTokenSigner, FreeRunAllowance


class GetFreeRunsUseCase:
    """Tells a device how many free runs it has left today, issuing it a
    device token first if it has none (or one this server didn't sign).

    Read-only by contract: asking never spends a run. Issuing a token is
    free and stateless - nothing is stored until a run is actually taken.
    """

    def __init__(self, *, free_runs: FreeRunAllowance, device_tokens: DeviceTokenSigner) -> None:
        self._free_runs = free_runs
        self._device_tokens = device_tokens

    async def execute(self, device_token: str | None) -> tuple[str, FreeRunStatus]:
        token = (device_token or "").strip()
        device_id = self._device_tokens.verify(token)
        if device_id is None:
            token = self._device_tokens.issue()
            device_id = self._device_tokens.verify(token)
            assert device_id is not None
        return token, await self._free_runs.status(device_id)
