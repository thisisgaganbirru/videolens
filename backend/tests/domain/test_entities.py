import unittest
from datetime import datetime, timezone

from app.domain.entities import AuthMethod, Principal, Run, RunStatus
from app.domain.entitlements import Plan


class PrincipalTests(unittest.TestCase):
    def test_anonymous_owner_is_the_subject(self) -> None:
        principal = Principal(subject="client:abc", authenticated=False)
        self.assertEqual(principal.owner_id, "client:abc")
        self.assertIs(principal.method, AuthMethod.ANONYMOUS)
        self.assertIs(principal.plan, Plan.FREE)

    def test_workspace_member_owner_is_the_workspace(self) -> None:
        principal = Principal(
            subject="user:u1",
            authenticated=True,
            method=AuthMethod.TOKEN,
            workspace_id="ws1",
            plan=Plan.PRO,
        )
        self.assertEqual(principal.owner_id, "workspace:ws1")


class RunCompatibilityTests(unittest.TestCase):
    def test_pre_workspace_payload_still_validates(self) -> None:
        now = datetime.now(timezone.utc)
        run = Run.model_validate(
            {
                "run_id": "r1",
                "owner_id": "client:abc",
                "status": "queued",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        )
        self.assertIs(run.status, RunStatus.QUEUED)
        self.assertIsNone(run.workspace_id)
        self.assertIs(run.plan, Plan.FREE)
        self.assertIsNone(run.max_duration_seconds)
        self.assertIsNone(run.usage)


if __name__ == "__main__":
    unittest.main()
