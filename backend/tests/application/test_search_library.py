import unittest
from datetime import datetime, timedelta, timezone

from app.application.search_library import MAX_LIMIT, SearchLibraryUseCase
from app.domain.entities import AuthMethod, Principal, SourceMetadata, VideoAnalysis

from .fakes import FakeRunArchive, FakeRunRepository

ANON = Principal(subject="client:anon", authenticated=False)
MEMBER = Principal(
    subject="user:x", authenticated=True, method=AuthMethod.TOKEN, account_id="acct-1", workspace_id="ws-pro"
)


def _analysis(title: str, transcript: str = "") -> VideoAnalysis:
    return VideoAnalysis(title=title, summary=f"About {title}", transcript=transcript, screen_text="", markdown="")


class SearchLibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runs = FakeRunRepository()
        self.archive = FakeRunArchive(enabled=False)
        self.use_case = SearchLibraryUseCase(runs=self.runs, archive=self.archive)
        for index, (title, platform) in enumerate(
            [("Sourdough starter", "YouTube"), ("Pasta night", "Instagram"), ("Bread scoring", "TikTok")]
        ):
            run = await self.runs.create(f"run-{index}", ANON.owner_id)
            await self.runs.set_result(run.run_id, _analysis(title, "flour water salt" if index == 0 else ""))
            await self.runs.set_source_metadata(
                run.run_id, SourceMetadata(platform=platform, source_url="https://x.test", title=title)
            )
            run.created_at = datetime(2026, 9, 1 + index, tzinfo=timezone.utc)

    async def test_without_an_archive_it_matches_over_recent_history(self) -> None:
        by_title = await self.use_case.execute(ANON, query="  BREAD ")
        by_transcript = await self.use_case.execute(ANON, query="water")
        everything = await self.use_case.execute(ANON)

        self.assertEqual([run.run_id for run in by_title], ["run-2"])
        self.assertEqual([run.run_id for run in by_transcript], ["run-0"])
        self.assertEqual(len(everything), 3)

    async def test_filters_by_platform_and_date_range(self) -> None:
        by_platform = await self.use_case.execute(ANON, platform="instagram")
        since = await self.use_case.execute(ANON, since=datetime(2026, 9, 2, tzinfo=timezone.utc))
        until = await self.use_case.execute(ANON, until=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))

        self.assertEqual([run.run_id for run in by_platform], ["run-1"])
        self.assertEqual({run.run_id for run in since}, {"run-1", "run-2"})
        self.assertEqual([run.run_id for run in until], ["run-0"])

    async def test_pages_and_clamps_the_limit(self) -> None:
        page = await self.use_case.execute(ANON, limit=1, offset=1)
        clamped = await self.use_case.execute(ANON, limit=10_000, offset=-5)

        self.assertEqual(len(page), 1)
        self.assertEqual(len(clamped), 3)

    async def test_a_workspace_with_an_archive_searches_the_archive(self) -> None:
        archive = FakeRunArchive(enabled=True)
        archived = await self.runs.create("archived", MEMBER.owner_id)
        archive.results = [archived]
        use_case = SearchLibraryUseCase(runs=self.runs, archive=archive)
        since = datetime.now(timezone.utc) - timedelta(days=7)

        results = await use_case.execute(MEMBER, query=" bread ", platform="TikTok", since=since, limit=500)

        self.assertEqual(results, [archived])
        self.assertEqual(
            archive.searches,
            [
                dict(
                    owner_id="workspace:ws-pro",
                    query="bread",
                    platform="tiktok",
                    since=since,
                    until=None,
                    limit=MAX_LIMIT,
                    offset=0,
                )
            ],
        )

    async def test_anonymous_callers_never_hit_the_archive(self) -> None:
        archive = FakeRunArchive(enabled=True)
        use_case = SearchLibraryUseCase(runs=self.runs, archive=archive)

        results = await use_case.execute(ANON, query="bread")

        self.assertEqual([run.run_id for run in results], ["run-2"])
        self.assertEqual(archive.searches, [])


if __name__ == "__main__":
    unittest.main()
