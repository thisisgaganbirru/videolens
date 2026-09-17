import unittest

from app.application.api_keys import MAX_ACTIVE_KEYS, ManageApiKeysUseCase
from app.domain.entities import AuthMethod, Principal
from app.domain.entitlements import Plan
from app.domain.errors import ApiKeyNotFoundError, PermissionDeniedError, WorkspaceNotFoundError

from .fakes import FakeAccountDirectory, FakeApiKeyRepository, make_entitlements, make_workspace


def _principal(account_id: str = "acct-1", plan: Plan = Plan.STUDIO) -> Principal:
    return Principal(
        subject="user:x",
        authenticated=True,
        method=AuthMethod.TOKEN,
        account_id=account_id,
        workspace_id="ws-pro",
        plan=plan,
    )


class ManageApiKeysTests(unittest.IsolatedAsyncioTestCase):
    def _make(self, plan: Plan = Plan.STUDIO) -> ManageApiKeysUseCase:
        self.accounts = FakeAccountDirectory()
        self.accounts.add_workspace(make_workspace(plan=plan), members={"acct-2": "member"})
        self.api_keys = FakeApiKeyRepository()
        return ManageApiKeysUseCase(
            api_keys=self.api_keys,
            accounts=self.accounts,
            entitlements=make_entitlements(accounts=self.accounts),
        )

    async def test_owner_issues_lists_and_revokes_keys(self) -> None:
        use_case = self._make()

        issued = await use_case.issue(_principal(), "  CI runner  ")
        listed = await use_case.list(_principal())
        await use_case.revoke(_principal(), issued.key.key_id)
        after = await use_case.list(_principal())

        self.assertTrue(issued.secret.startswith("vl_live_"))
        self.assertEqual(issued.key.name, "CI runner")
        self.assertEqual(issued.key.scopes, ["runs:write", "runs:read"])
        self.assertEqual([key.key_id for key in listed], [issued.key.key_id])
        self.assertFalse(after[0].active)

    async def test_blank_names_get_a_default(self) -> None:
        use_case = self._make()
        issued = await use_case.issue(_principal(), "   ")
        self.assertEqual(issued.key.name, "Unnamed key")

    async def test_anonymous_callers_have_no_workspace(self) -> None:
        use_case = self._make()
        with self.assertRaises(WorkspaceNotFoundError):
            await use_case.list(Principal(subject="client:x", authenticated=False))

    async def test_plans_without_api_access_are_refused(self) -> None:
        use_case = self._make(plan=Plan.PRO)
        with self.assertRaises(PermissionDeniedError):
            await use_case.list(_principal(plan=Plan.PRO))
        with self.assertRaises(PermissionDeniedError):
            await use_case.issue(_principal(plan=Plan.PRO), "x")

    async def test_members_can_list_but_not_issue_or_revoke(self) -> None:
        use_case = self._make()
        issued = await use_case.issue(_principal(), "x")

        listed = await use_case.list(_principal(account_id="acct-2"))
        self.assertEqual(len(listed), 1)
        with self.assertRaises(PermissionDeniedError):
            await use_case.issue(_principal(account_id="acct-2"), "y")
        with self.assertRaises(PermissionDeniedError):
            await use_case.revoke(_principal(account_id="acct-2"), issued.key.key_id)

    async def test_revoking_an_unknown_key_is_not_found(self) -> None:
        use_case = self._make()
        with self.assertRaises(ApiKeyNotFoundError):
            await use_case.revoke(_principal(), "key-404")

    async def test_active_keys_are_capped(self) -> None:
        use_case = self._make()
        for index in range(MAX_ACTIVE_KEYS):
            await use_case.issue(_principal(), f"key {index}")

        with self.assertRaises(PermissionDeniedError):
            await use_case.issue(_principal(), "one too many")

        # Revoking one frees a slot: the cap is on active keys, not history.
        await use_case.revoke(_principal(), "key-1")
        await use_case.issue(_principal(), "replacement")


if __name__ == "__main__":
    unittest.main()
