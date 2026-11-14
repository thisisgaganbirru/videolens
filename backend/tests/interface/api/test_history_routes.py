"""`/api/history` and `/api/me`'s `saved_history`, end to end through
FastAPI (docs/backend/saved-history.md). Identity, billing and saved runs
are in-memory; the bearer token is whatever the fake verifier says."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from starlette.testclient import TestClient

from app.application.billing import BillingPlans
from app.application.create_api_key import CreateApiKeyUseCase
from app.application.entitlements import EntitlementResolver
from app.application.get_account import GetAccountUseCase
from app.application.identify_caller import IdentifyCallerUseCase
from app.application.saved_history import SavedHistory, SavedHistoryQueries
from app.container import container
from app.domain.entities import SavedRun, SavedRunSource, SubscriptionSnapshot
from app.infrastructure.config import Settings
from app.infrastructure.persistence.account_directory import InMemoryAccountDirectory
from app.infrastructure.persistence.api_key_repository import InMemoryApiKeyRepository
from app.infrastructure.persistence.billing_store import InMemoryBillingAccounts, InMemoryExtraRunLedger
from app.infrastructure.persistence.run_repository import RunStore
from app.infrastructure.persistence.saved_run_repository import InMemorySavedRuns
from app.interface.api.app import app

SETTINGS = Settings(_env_file=None, gemini_api_key="k")
TOKEN = {"Authorization": "Bearer eyJhbGciOi.payload.signature"}
ANON = {"X-Client-ID": "test-client-0123456789"}
NOW = datetime.now(timezone.utc)


class FakeTokenVerifier:
    def __init__(self, claims: dict) -> None:
        self.claims = claims

    def decode(self, token: str) -> dict:
        return dict(self.claims)


class EnabledGateway:
    """Only `enabled` is read on these paths."""

    enabled = True


POSTER = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def _saved(account_id: str, run_id: str, minutes_ago: int = 0, thumbnail: str | None = None) -> SavedRun:
    return SavedRun(
        run_id=run_id,
        account_id=account_id,
        title=f"Title {run_id}",
        summary_snippet="Snippet",
        source=SavedRunSource(source_kind="link", platform="youtube", source_url="https://youtu.be/x"),
        result={
            "title": f"Title {run_id}",
            "summary": "Summary",
            "transcript": "Words",
            "screen_text": "",
            "markdown": "# T",
        },
        completeness="full",
        created_at=NOW - timedelta(minutes=minutes_ago),
        thumbnail=thumbnail,
    )


class HistoryRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = FakeTokenVerifier({"sub": "user-123", "email": "a@b.test", "role": "authenticated"})
        self.accounts = InMemoryAccountDirectory()
        keys = InMemoryApiKeyRepository()
        self.billing_accounts = InMemoryBillingAccounts(SETTINGS)
        plans = BillingPlans(
            gateway=EnabledGateway(),
            accounts=self.billing_accounts,
            ledger=InMemoryExtraRunLedger(SETTINGS),
            paid_runs_per_day=30,
            extra_runs_monthly_cap=200,
        )
        self.saved = InMemorySavedRuns(SETTINGS, accounts=self.accounts)
        history = SavedHistory(runs=RunStore(SETTINGS), saved_runs=self.saved, plans=plans)
        replacements = {
            "identify_caller_use_case": IdentifyCallerUseCase(
                accounts=self.accounts, api_keys=keys, verifier=self.verifier, allow_anonymous=True
            ),
            "get_account_use_case": GetAccountUseCase(
                accounts=self.accounts,
                entitlements=EntitlementResolver(max_duration_seconds=180, max_file_size_mb=200),
                history=history,
            ),
            "create_api_key_use_case": CreateApiKeyUseCase(api_keys=keys, accounts=self.accounts, max_active=2),
            "saved_history_queries": SavedHistoryQueries(history=history),
        }
        patcher = patch.multiple(container, **replacements)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)
        self.account_id = self.client.get("/api/me", headers=TOKEN).json()["account_id"]

    def _run(self, coroutine):
        return asyncio.run(coroutine)

    def _subscribe(self, status: str = "active") -> None:
        async def go() -> None:
            await self.billing_accounts.link_customer(self.account_id, "cus_1")
            await self.billing_accounts.apply_subscription(
                self.account_id,
                SubscriptionSnapshot(
                    subscription_id="sub_1",
                    customer_id="cus_1",
                    status=status,
                    price_id="price_m",
                    interval="month",
                    current_period_end=NOW + timedelta(days=20),
                    cancel_at_period_end=False,
                ),
            )

        self._run(go())

    def _save(self, account_id: str, run_id: str, minutes_ago: int = 0, thumbnail: str | None = None) -> None:
        self._run(self.saved.save(_saved(account_id, run_id, minutes_ago, thumbnail)))

    def test_anonymous_is_401_and_an_api_key_is_403(self) -> None:
        secret = self.client.post("/api/keys", headers=TOKEN, json={"name": "ci"}).json()["secret"]
        for method, path in (("get", "/api/history"), ("get", "/api/history/r"), ("delete", "/api/history")):
            with self.subTest(path=path, method=method):
                self.assertEqual(getattr(self.client, method)(path, headers=ANON).status_code, 401)
                self.assertEqual(getattr(self.client, method)(path, headers={"X-Api-Key": secret}).status_code, 403)

    def test_a_free_account_gets_an_empty_list_and_saving_false(self) -> None:
        response = self.client.get("/api/history", headers=TOKEN)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"saving": False, "expires_at": None, "items": [], "next_cursor": None})
        me = self.client.get("/api/me", headers=TOKEN).json()
        self.assertEqual(me["saved_history"], {"saving": False, "expires_at": None})

    def test_a_paid_account_lists_pages_gets_and_deletes(self) -> None:
        self._subscribe()
        for index in range(3):
            self._save(self.account_id, f"run-{index}", minutes_ago=index)
        self._save("someone-else", "theirs")
        self.assertEqual(self.client.get("/api/me", headers=TOKEN).json()["saved_history"]["saving"], True)

        first = self.client.get("/api/history?limit=2", headers=TOKEN).json()
        self.assertTrue(first["saving"])
        self.assertEqual([i["run_id"] for i in first["items"]], ["run-0", "run-1"])
        item = first["items"][0]
        self.assertEqual(item["title"], "Title run-0")
        self.assertEqual(item["summary_snippet"], "Snippet")
        self.assertEqual(item["source"]["platform"], "youtube")
        self.assertNotIn("result", item)
        second = self.client.get(f"/api/history?limit=2&cursor={first['next_cursor']}", headers=TOKEN).json()
        self.assertEqual([i["run_id"] for i in second["items"]], ["run-2"])
        self.assertIsNone(second["next_cursor"])

        full = self.client.get("/api/history/run-0", headers=TOKEN)
        self.assertEqual(full.status_code, 200, full.text)
        self.assertEqual(full.json()["result"]["transcript"], "Words")
        self.assertEqual(self.client.get("/api/history/theirs", headers=TOKEN).status_code, 404)

        self.assertEqual(self.client.delete("/api/history/run-0", headers=TOKEN).status_code, 204)
        self.assertEqual(self.client.delete("/api/history/run-0", headers=TOKEN).status_code, 404)
        self.assertEqual(self.client.delete("/api/history/theirs", headers=TOKEN).status_code, 404)
        self.assertEqual(self.client.delete("/api/history", headers=TOKEN).json(), {"deleted": 2})
        self.assertEqual(self._run(self.saved.count("someone-else")), 1)

    def test_the_poster_is_on_list_items_and_the_detail_as_thumbnail(self) -> None:
        self._subscribe()
        self._save(self.account_id, "with", minutes_ago=1, thumbnail=POSTER)
        self._save(self.account_id, "without")

        items = self.client.get("/api/history", headers=TOKEN).json()["items"]
        self.assertEqual([(i["run_id"], i["thumbnail"]) for i in items], [("without", None), ("with", POSTER)])
        for item in items:
            self.assertIn("thumbnail", item)  # always present, null when none
            self.assertNotIn("thumbnail", item["source"])
        self.assertEqual(self.client.get("/api/history/with", headers=TOKEN).json()["thumbnail"], POSTER)
        detail = self.client.get("/api/history/without", headers=TOKEN).json()
        self.assertIn("thumbnail", detail)
        self.assertIsNone(detail["thumbnail"])

    def test_the_post_cancel_window_shows_its_expiry(self) -> None:
        self._subscribe("canceled")
        self._save(self.account_id, "run-1")
        expires = NOW + timedelta(days=12)
        self._run(self.saved.arm_expiry(self.account_id, expires))

        body = self.client.get("/api/history", headers=TOKEN).json()
        self.assertFalse(body["saving"])
        self.assertEqual([i["run_id"] for i in body["items"]], ["run-1"])
        self.assertEqual(datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00")), expires)
        me = self.client.get("/api/me", headers=TOKEN).json()["saved_history"]
        self.assertEqual(me["expires_at"], body["expires_at"])

    def test_bad_paging_is_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/history?cursor=%21%21nope", headers=TOKEN).status_code, 400)
        self.assertEqual(self.client.get("/api/history?limit=0", headers=TOKEN).status_code, 422)
        self.assertEqual(self.client.get("/api/history?limit=101", headers=TOKEN).status_code, 422)


if __name__ == "__main__":
    unittest.main()
