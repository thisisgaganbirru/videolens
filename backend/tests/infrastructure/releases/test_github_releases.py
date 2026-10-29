import unittest

from app.infrastructure.config import Settings
from app.infrastructure.releases.github_releases import GithubReleaseCatalog

PAYLOAD = [
    {
        "name": "VideoLens AI dev build v2.0.9 (#24)",
        "tag_name": "dev-v2.0.9-build24",
        "published_at": "2026-08-29T20:10:00Z",
        "html_url": "https://github.com/o/r/releases/tag/dev-v2.0.9-build24",
        "draft": False,
    },
    {
        "name": "VideoLens AI dev build v2.0.8 (#17)",
        "tag_name": "dev-v2.0.8-build17",
        "published_at": "2026-08-21T08:00:00Z",
        "html_url": "https://github.com/o/r/releases/tag/dev-v2.0.8-build17",
        "draft": False,
    },
]


MAIN_PAYLOAD = [
    {
        "name": "VideoLens AI v2.1.0 (build 182)",
        "tag_name": "v2.1.0-build182",
        "published_at": "2026-09-01T10:00:00Z",
        "html_url": "https://github.com/o/r/releases/tag/v2.1.0-build182",
        "draft": False,
    },
    *PAYLOAD,
]


class ToIndexTests(unittest.TestCase):
    def test_reads_a_release_published_from_main(self) -> None:
        # Releases moved from dev to main and lost the `dev-` prefix with it.
        index = GithubReleaseCatalog._to_index(MAIN_PAYLOAD)

        self.assertEqual(index.latest.version_code, 182)
        self.assertEqual(index.latest.version_name, "2.1.0")

    def test_still_reads_the_dev_prefixed_tags_already_published(self) -> None:
        # Builds 1-30 shipped as `dev-v<version>-build<code>` and are still the
        # newest thing a device out there has installed. If they stopped
        # parsing, `latest` would fall through to None and those devices would
        # never be offered anything.
        index = GithubReleaseCatalog._to_index(PAYLOAD)

        self.assertEqual(index.latest.version_code, 24)

    def test_maps_every_release_into_the_index(self) -> None:
        index = GithubReleaseCatalog._to_index(PAYLOAD)

        self.assertEqual(len(index.releases), 2)
        self.assertEqual(index.releases[0].tag, "dev-v2.0.9-build24")
        self.assertEqual(index.releases[0].published_at, "2026-08-29T20:10:00Z")

    def test_derives_the_latest_build_from_the_tag(self) -> None:
        # The Android update check compares versionCode, which only exists in
        # the tag - the release name is prose.
        index = GithubReleaseCatalog._to_index(PAYLOAD)

        self.assertEqual(index.latest.version_code, 24)
        self.assertEqual(index.latest.version_name, "2.0.9")
        self.assertIn("build24", index.latest.url)

    def test_takes_the_newest_parseable_tag_as_latest(self) -> None:
        payload = [{"tag_name": "some-manual-tag", "html_url": "u", "draft": False}, *PAYLOAD]

        index = GithubReleaseCatalog._to_index(payload)

        # The unparseable release is still listed, it just cannot answer
        # "is there an update".
        self.assertEqual(len(index.releases), 3)
        self.assertEqual(index.latest.version_code, 24)

    def test_reports_no_latest_when_nothing_matches_the_tag_scheme(self) -> None:
        index = GithubReleaseCatalog._to_index([{"tag_name": "v1", "html_url": "u", "draft": False}])

        self.assertIsNone(index.latest)
        self.assertEqual(len(index.releases), 1)

    def test_skips_drafts(self) -> None:
        payload = [{"tag_name": "dev-v9.9.9-build99", "html_url": "u", "draft": True}, *PAYLOAD]

        index = GithubReleaseCatalog._to_index(payload)

        self.assertEqual(len(index.releases), 2)
        self.assertEqual(index.latest.version_code, 24)

    def test_falls_back_to_the_tag_when_a_release_has_no_name(self) -> None:
        index = GithubReleaseCatalog._to_index(
            [{"tag_name": "dev-v1.0.0-build1", "html_url": "u", "draft": False}]
        )

        self.assertEqual(index.releases[0].name, "dev-v1.0.0-build1")

    def test_an_empty_payload_is_an_empty_index(self) -> None:
        index = GithubReleaseCatalog._to_index([])

        self.assertEqual(index.releases, [])
        self.assertIsNone(index.latest)


class ConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unconfigured_catalog_returns_empty_without_calling_github(self) -> None:
        # Same outcome the static manifest had before CI first ran: the
        # Releases tab is empty and the update check no-ops.
        catalog = GithubReleaseCatalog(Settings(github_token="", gemini_api_key="k"))

        self.assertFalse(catalog.configured)
        self.assertEqual((await catalog.fetch()).releases, [])

    async def test_a_token_and_repo_make_it_configured(self) -> None:
        catalog = GithubReleaseCatalog(Settings(github_token="t", gemini_api_key="k"))

        self.assertTrue(catalog.configured)

    async def test_a_blank_repo_is_not_configured(self) -> None:
        catalog = GithubReleaseCatalog(
            Settings(github_token="t", github_repo="", gemini_api_key="k")
        )

        self.assertFalse(catalog.configured)


if __name__ == "__main__":
    unittest.main()
