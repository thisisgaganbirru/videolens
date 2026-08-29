import unittest

from app.application.get_releases import GetReleasesUseCase
from app.domain.entities import ReleaseEntry, ReleaseIndex

INDEX = ReleaseIndex(
    releases=[ReleaseEntry(name="n", tag="dev-v1.0.0-build1", published_at="d", url="u")]
)


class FakeCatalog:
    def __init__(self, index=INDEX, error: Exception | None = None) -> None:
        self.index = index
        self.error = error
        self.calls = 0

    async def fetch(self) -> ReleaseIndex:
        self.calls += 1
        if self.error:
            raise self.error
        return self.index


class GetReleasesUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_catalog_index(self) -> None:
        use_case = GetReleasesUseCase(catalog=FakeCatalog(), cache_seconds=0.0)

        self.assertEqual((await use_case.execute()).releases[0].tag, "dev-v1.0.0-build1")

    async def test_caches_so_every_client_poll_does_not_hit_github(self) -> None:
        # GitHub rate limits per token, not per caller, so an uncached
        # endpoint would let one busy page exhaust the budget for everyone.
        catalog = FakeCatalog()
        use_case = GetReleasesUseCase(catalog=catalog, cache_seconds=300.0)

        await use_case.execute()
        await use_case.execute()
        await use_case.execute()

        self.assertEqual(catalog.calls, 1)

    async def test_refetches_once_the_cache_expires(self) -> None:
        catalog = FakeCatalog()
        use_case = GetReleasesUseCase(catalog=catalog, cache_seconds=0.0)

        await use_case.execute()
        await use_case.execute()

        self.assertEqual(catalog.calls, 2)

    async def test_serves_the_last_good_answer_when_a_refresh_fails(self) -> None:
        catalog = FakeCatalog()
        use_case = GetReleasesUseCase(catalog=catalog, cache_seconds=0.0)
        await use_case.execute()

        catalog.error = RuntimeError("github is down")
        result = await use_case.execute()

        # A stale release list beats a broken Releases tab.
        self.assertEqual(result.releases[0].tag, "dev-v1.0.0-build1")

    async def test_an_empty_index_when_it_has_never_succeeded(self) -> None:
        use_case = GetReleasesUseCase(
            catalog=FakeCatalog(error=RuntimeError("boom")), cache_seconds=0.0
        )

        self.assertEqual((await use_case.execute()).releases, [])

    async def test_a_failure_never_propagates_to_the_caller(self) -> None:
        use_case = GetReleasesUseCase(
            catalog=FakeCatalog(error=RuntimeError("token expired")), cache_seconds=0.0
        )

        result = await use_case.execute()

        self.assertIsInstance(result, ReleaseIndex)


if __name__ == "__main__":
    unittest.main()
