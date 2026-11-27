import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from app.container import container
from app.domain.entities import Run, RunStatus, SlideKind, SlideVisual, SourceMetadata, VideoAnalysis
from app.interface.api.app import app

HEADERS = {"X-Client-ID": "test-client-0123456789"}
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

LINK_RUN = Run(
    run_id="link-1",
    owner_id="client:test-client-0123456789",
    status=RunStatus.COMPLETE,
    created_at=NOW,
    updated_at=NOW,
    source_kind="link",
    duration_seconds=58.0,
    source_metadata=SourceMetadata(
        platform="Youtube", source_url="https://www.youtube.com/shorts/abc", title="Clip"
    ),
    result=VideoAnalysis(
        title="A clip",
        summary="  A summary\nacross lines. ",
        transcript="",
        screen_text="",
        markdown="",
    ),
)

FILE_RUN = Run(
    run_id="file-1",
    owner_id="client:test-client-0123456789",
    status=RunStatus.PROCESSING,
    created_at=NOW,
    updated_at=NOW,
    source_kind="file",
    platform="audio_file",
    duration_seconds=12.5,
)

# Shape of a run written before these fields existed, parsed the way the
# Redis adapter parses it.
LEGACY_RUN = Run.model_validate_json(
    '{"run_id":"old-1","owner_id":"client:test-client-0123456789","status":"failed",'
    '"created_at":"2026-10-01T00:00:00Z","updated_at":"2026-10-01T00:00:00Z",'
    '"error":"nope","completeness":"full"}'
)


class RunRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_list_returns_the_poster_fields(self) -> None:
        with patch.object(
            container.list_runs_use_case,
            "execute",
            AsyncMock(return_value=[LINK_RUN, FILE_RUN, LEGACY_RUN]),
        ):
            response = self.client.get("/api/runs", headers=HEADERS)

        self.assertEqual(response.status_code, 200)
        link, file, legacy = response.json()["runs"]

        self.assertEqual(link["source_kind"], "link")
        self.assertEqual(link["platform"], "youtube")
        self.assertEqual(link["orientation"], "portrait")  # a /shorts/ URL
        self.assertEqual(link["duration_seconds"], 58.0)
        self.assertEqual(link["summary_snippet"], "A summary across lines.")
        self.assertEqual(link["title"], "A clip")

        self.assertEqual(file["source_kind"], "file")
        self.assertEqual(file["platform"], "audio_file")
        self.assertEqual(file["orientation"], "portrait")
        self.assertIsNone(file["summary_snippet"])

        for field in ("source_kind", "platform", "duration_seconds", "summary_snippet", "orientation"):
            with self.subTest(field=field):
                self.assertIn(field, legacy)
                self.assertIsNone(legacy[field])

    def test_status_returns_source_kind_platform_and_duration(self) -> None:
        with patch.object(
            container.get_run_use_case, "execute", AsyncMock(return_value=LINK_RUN)
        ):
            response = self.client.get("/api/runs/link-1", headers=HEADERS)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source_kind"], "link")
        self.assertEqual(body["platform"], "youtube")
        self.assertEqual(body["duration_seconds"], 58.0)
        self.assertNotIn("owner_id", body)

    def test_status_carries_the_history_poster(self) -> None:
        run = LINK_RUN.model_copy(
            update={"thumbnail": "data:image/jpeg;base64,/9j/AA==", "width": 1080, "height": 1920}
        )
        with patch.object(container.get_run_use_case, "execute", AsyncMock(return_value=run)):
            body = self.client.get("/api/runs/link-1", headers=HEADERS).json()

        self.assertEqual(body["thumbnail"], "data:image/jpeg;base64,/9j/AA==")
        self.assertEqual((body["width"], body["height"]), (1080, 1920))
        self.assertEqual(body["orientation"], "portrait")

    def test_a_carousel_reports_its_slide_count_in_status_and_list(self) -> None:
        run = LINK_RUN.model_copy(update={"slide_count": 5})
        with patch.object(container.get_run_use_case, "execute", AsyncMock(return_value=run)):
            body = self.client.get("/api/runs/link-1", headers=HEADERS).json()
        with patch.object(container.list_runs_use_case, "execute", AsyncMock(return_value=[run])):
            (item,) = self.client.get("/api/runs", headers=HEADERS).json()["runs"]

        self.assertEqual(body["slide_count"], 5)
        self.assertEqual(item["slide_count"], 5)

    def test_a_carousel_returns_its_slide_pictures_on_status_only(self) -> None:
        run = LINK_RUN.model_copy(
            update={
                "slide_count": 3,
                "slides": [
                    SlideVisual(slide=1, kind=SlideKind.VIDEO, thumbnail="data:image/jpeg;base64,AQ=="),
                    SlideVisual(slide=2, kind=SlideKind.IMAGE, thumbnail=None),
                    SlideVisual(slide=3, kind=SlideKind.IMAGE, thumbnail="data:image/jpeg;base64,Aw=="),
                ],
            }
        )
        with patch.object(container.get_run_use_case, "execute", AsyncMock(return_value=run)):
            body = self.client.get("/api/runs/link-1", headers=HEADERS).json()
        with patch.object(container.list_runs_use_case, "execute", AsyncMock(return_value=[run])):
            (item,) = self.client.get("/api/runs", headers=HEADERS).json()["runs"]

        self.assertEqual(
            body["slides"],
            [
                {"slide": 1, "kind": "video", "thumbnail": "data:image/jpeg;base64,AQ=="},
                {"slide": 2, "kind": "image", "thumbnail": None},
                {"slide": 3, "kind": "image", "thumbnail": "data:image/jpeg;base64,Aw=="},
            ],
        )
        # 20 rows of inline pictures would make every history poll heavy.
        self.assertNotIn("slides", item)

    def test_a_single_file_run_has_null_slides(self) -> None:
        for run in (LINK_RUN, FILE_RUN, LEGACY_RUN):
            with self.subTest(run=run.run_id), patch.object(
                container.get_run_use_case, "execute", AsyncMock(return_value=run)
            ):
                body = self.client.get(f"/api/runs/{run.run_id}", headers=HEADERS).json()
                self.assertIn("slides", body)
                self.assertIsNone(body["slides"])

    def test_status_of_a_legacy_run_has_null_poster_fields(self) -> None:
        with patch.object(container.get_run_use_case, "execute", AsyncMock(return_value=LEGACY_RUN)):
            body = self.client.get("/api/runs/old-1", headers=HEADERS).json()

        for field in ("thumbnail", "width", "height", "orientation", "slide_count"):
            with self.subTest(field=field):
                self.assertIn(field, body)
                self.assertIsNone(body[field])

    def test_list_has_dimensions_but_never_the_thumbnail(self) -> None:
        run = FILE_RUN.model_copy(
            update={
                "thumbnail": "data:image/jpeg;base64,/9j/AA==",
                "width": 1920,
                "height": 1080,
                "platform": "video_file",
            }
        )
        with patch.object(container.list_runs_use_case, "execute", AsyncMock(return_value=[run])):
            (item,) = self.client.get("/api/runs", headers=HEADERS).json()["runs"]

        self.assertNotIn("thumbnail", item)
        self.assertEqual((item["width"], item["height"]), (1920, 1080))
        self.assertEqual(item["orientation"], "landscape")


if __name__ == "__main__":
    unittest.main()
