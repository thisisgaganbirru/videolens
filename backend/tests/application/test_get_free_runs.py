import unittest

from app.application.get_free_runs import GetFreeRunsUseCase
from app.domain.entities import AuthMethod, FreeRunScope, Principal

from .fakes import FakeAccountFreeRunAllowance, FakeDeviceTokens, FakeFreeRunAllowance

PERSON = Principal(subject="user:sub-1", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1")
ANON = Principal(subject="client:x", authenticated=False)


class GetFreeRunsUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def _make(self, *, enabled: bool = True, wired: bool = True) -> GetFreeRunsUseCase:
        self.devices = FakeFreeRunAllowance()
        self.accounts = FakeAccountFreeRunAllowance(enabled=enabled)
        self.tokens = FakeDeviceTokens()
        return GetFreeRunsUseCase(
            free_runs=self.devices, device_tokens=self.tokens, account_free_runs=self.accounts if wired else None
        )

    async def test_anonymous_gets_the_device_standing(self) -> None:
        token, status = await self._make().execute(None, None)
        self.assertEqual(token, "good:device-1")
        self.assertEqual(status.scope, FreeRunScope.DEVICE)
        _, status = await self._make().execute("good:dev-a", ANON)
        self.assertEqual(status.scope, FreeRunScope.DEVICE)

    async def test_a_signed_in_account_gets_the_account_standing_and_still_a_token(self) -> None:
        use_case = self._make()
        await self.accounts.try_consume("acct-1")
        token, status = await use_case.execute(None, PERSON)
        self.assertEqual(token, "good:device-1")
        self.assertEqual((status.scope, status.limit, status.used, status.remaining), (FreeRunScope.ACCOUNT, 10, 1, 9))
        self.assertEqual(self.accounts.consume_calls, 1)  # read-only

    async def test_a_genuine_token_is_echoed(self) -> None:
        token, _ = await self._make().execute("good:dev-a", PERSON)
        self.assertEqual(token, "good:dev-a")

    async def test_falls_back_to_the_device_when_the_account_allowance_is_off_or_unwired(self) -> None:
        _, status = await self._make(enabled=False).execute(None, PERSON)
        self.assertEqual(status.scope, FreeRunScope.DEVICE)
        _, status = await self._make(wired=False).execute(None, PERSON)
        self.assertEqual(status.scope, FreeRunScope.DEVICE)

    async def test_signed_in_without_an_account_store_gets_the_device_standing(self) -> None:
        bare = Principal(subject="user:sub-2", authenticated=True, method=AuthMethod.TOKEN)
        _, status = await self._make().execute(None, bare)
        self.assertEqual(status.scope, FreeRunScope.DEVICE)


if __name__ == "__main__":
    unittest.main()
