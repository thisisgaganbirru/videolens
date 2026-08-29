import unittest

from app.domain.entities import SavedUpload, SourceMetadata
from app.domain.errors import MediaValidationError
from app.infrastructure.media.resolvers import ResolverChain


class FakeResolver:
    def __init__(
        self,
        name: str,
        *,
        handles: bool = True,
        error: Exception | None = None,
        metadata: SourceMetadata | None = None,
    ) -> None:
        self._name = name
        self._handles = handles
        self._error = error
        self._metadata = metadata
        self.fetches: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return self._name

    def can_handle(self, url: str) -> bool:
        return self._handles

    async def fetch(self, run_id: str, url: str) -> SavedUpload:
        self.fetches.append((run_id, url))
        if self._error:
            raise self._error
        return SavedUpload(
            path=f"/tmp/{run_id}/{self._name}.mp4",
            run_dir=f"/tmp/{run_id}",
            metadata=self._metadata,
        )


class ResolverChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_first_resolver_that_succeeds(self) -> None:
        first = FakeResolver("first")
        second = FakeResolver("second")

        saved = await ResolverChain([first, second]).fetch("run-1", "https://x.test/v.mp4")

        self.assertEqual(saved.path, "/tmp/run-1/first.mp4")
        self.assertEqual(len(first.fetches), 1)
        # The fallback is never consulted once the primary works.
        self.assertEqual(second.fetches, [])

    async def test_falls_through_to_the_next_resolver_on_failure(self) -> None:
        first = FakeResolver("first", error=MediaValidationError("extractor is broken"))
        second = FakeResolver("second")

        saved = await ResolverChain([first, second]).fetch("run-1", "https://x.test/v.mp4")

        self.assertEqual(saved.path, "/tmp/run-1/second.mp4")
        self.assertEqual(len(second.fetches), 1)

    async def test_skips_resolvers_that_do_not_claim_the_url(self) -> None:
        skipped = FakeResolver("skipped", handles=False)
        used = FakeResolver("used")

        await ResolverChain([skipped, used]).fetch("run-1", "https://x.test/watch?v=1")

        self.assertEqual(skipped.fetches, [])
        self.assertEqual(len(used.fetches), 1)

    async def test_reports_the_primary_resolvers_error_when_every_route_fails(self) -> None:
        # yt-dlp's curated guidance ("configure cookies…") is far more useful
        # than a fallback's generic 404, so the first failure is the one the
        # caller sees.
        first = FakeResolver("yt-dlp", error=MediaValidationError("Configure cookies for Instagram."))
        second = FakeResolver("direct-http", error=MediaValidationError("HTTP 404"))

        with self.assertRaisesRegex(MediaValidationError, "Configure cookies"):
            await ResolverChain([first, second]).fetch("run-1", "https://x.test/v.mp4")

    async def test_reports_a_clear_error_when_no_resolver_claims_the_url(self) -> None:
        chain = ResolverChain([FakeResolver("a", handles=False)])

        with self.assertRaisesRegex(MediaValidationError, "No downloader"):
            await chain.fetch("run-1", "gopher://x.test/v")

    async def test_preserves_metadata_from_whichever_resolver_succeeds(self) -> None:
        metadata = SourceMetadata(platform="YouTube", source_url="https://x.test/v")
        first = FakeResolver("first", error=MediaValidationError("nope"))
        second = FakeResolver("second", metadata=metadata)

        saved = await ResolverChain([first, second]).fetch("run-1", "https://x.test/v.mp4")

        self.assertEqual(saved.metadata, metadata)

    async def test_a_non_media_error_is_not_swallowed_by_the_chain(self) -> None:
        # Only MediaValidationError means "this route did not work". A bug
        # must not be silently retried away on the next resolver.
        first = FakeResolver("first", error=RuntimeError("programming error"))
        second = FakeResolver("second")

        with self.assertRaises(RuntimeError):
            await ResolverChain([first, second]).fetch("run-1", "https://x.test/v.mp4")
        self.assertEqual(second.fetches, [])

    def test_an_empty_chain_is_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            ResolverChain([])


if __name__ == "__main__":
    unittest.main()
