import asyncio
import json
from typing import Optional

from google import genai
from google.genai import types

from ...domain.entities import VideoAnalysis
from ...domain.errors import AnalysisUnavailableError, GeminiConfigurationError
from ...domain.ports import StageCallback
from ..config import Settings

SYSTEM_INSTRUCTION = """You are analyzing a short media file. It may be audio-only or a video.

Analyze the entire file and:
- Transcribe all spoken content.
- For video, read and capture all visible on-screen text: captions, code, UI labels, slides, charts, overlays.
- For video, understand visual actions and on-screen elements even when nothing is said about them out loud.
- Combine speech and visuals into one coherent explanation of what the video communicates,
  rather than describing the audio and the visuals as two separate, disconnected things.
- For audio-only input, leave screen_text empty and focus on the spoken or audible content.
- The video may be in English, Spanish, or Hindi. Keep the transcript in its original language.

Use timestamps measured from the start of the media. Keep them accurate to the nearest second.
Group spoken content into natural, short segments and identify a speaker only when their identity
or role is reasonably clear. For on-screen text, create a new segment whenever the visible text
meaningfully changes. Do not invent text that is not legible.

Return your analysis in the requested structured format:
- title: a short descriptive title for the video
- summary: a 2-4 sentence plain-prose abstract that answers "is this worth my time?".
  No headings, no bullet points, no markdown formatting at all. State what the video is
  about and what a viewer would take away from it. This is the shortest read, so do not
  restate the notes here - it is an orientation, not a condensed copy of them.
- transcript: the full spoken transcript
- transcript_segments: timestamped spoken segments with start_seconds, end_seconds, text, and optional speaker
- screen_text: the important on-screen text, in the order it appears
- screen_text_segments: timestamped visible-text segments with start_seconds, end_seconds, and text
- markdown: structured markdown notes complete enough to stand in for watching the video.
  Use headings and bullet points. Cover the key points in the order they are made, any
  steps or instructions given, code, figures, names and numbers shown on screen, and the
  conclusion the video reaches. Include the detail the summary deliberately leaves out -
  these two fields are read side by side, so they must not be two versions of the same
  paragraph."""


class GeminiEngine:
    """AnalysisEngine adapter backed by the Gemini API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: genai.Client | None = None

    def _get_client(self, api_key: str | None = None) -> genai.Client:
        # A caller-supplied (bring-your-own) key gets its own client, never cached
        # on this instance - that cache is only for the shared server key, and
        # must never end up holding someone else's credential.
        if api_key:
            return genai.Client(api_key=api_key)

        if not self._settings.gemini_api_key.strip():
            raise GeminiConfigurationError(
                "Analysis is temporarily unavailable.",
                log_detail=(
                    "GEMINI_API_KEY is not set and the caller supplied no key of their "
                    "own. Set GEMINI_API_KEY on the API and worker services."
                ),
            )
        if self._client is None:
            self._client = genai.Client(api_key=self._settings.gemini_api_key)
        return self._client

    async def _wait_until_active(self, client: genai.Client, file_name: str, timeout: float = 120.0) -> None:
        elapsed = 0.0
        interval = 2.0
        while elapsed < timeout:
            file = await client.aio.files.get(name=file_name)
            if file.state == types.FileState.ACTIVE:
                return
            if file.state == types.FileState.FAILED:
                raise RuntimeError("Gemini failed to process the uploaded video file.")
            await asyncio.sleep(interval)
            elapsed += interval
        raise RuntimeError("Timed out waiting for Gemini to finish processing the uploaded video.")

    async def _analyze(
        self, video_path: str, on_stage: Optional[StageCallback] = None, api_key: str | None = None
    ) -> VideoAnalysis:
        if on_stage:
            await on_stage("uploading_to_gemini")
        client = self._get_client(api_key)

        uploaded = await client.aio.files.upload(file=video_path)
        try:
            await self._wait_until_active(client, uploaded.name)

            if on_stage:
                await on_stage("analyzing")
            response = await client.aio.models.generate_content(
                model=self._settings.gemini_model,
                contents=[uploaded, "Analyze this media file as instructed."],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=VideoAnalysis,
                ),
            )

            if isinstance(response.parsed, VideoAnalysis):
                return response.parsed

            if not response.text:
                raise RuntimeError("Gemini returned an empty response.")
            return VideoAnalysis(**json.loads(response.text))
        finally:
            try:
                await client.aio.files.delete(name=uploaded.name)
            except Exception:
                pass

    # 429 and 5xx are the API saying "not now" - the request was well-formed and
    # the media was fine, so the honest advice is to wait rather than to go and
    # re-pick a file. Everything else stays an unexpected error and is masked by
    # ProcessRunUseCase, which logs the traceback.
    _TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})

    @classmethod
    def _as_domain_error(cls, exc: Exception) -> Exception:
        status = getattr(exc, "code", None)
        if status in cls._TRANSIENT_STATUS:
            message = (
                "Too many requests right now. Try again in a moment."
                if status == 429
                else "Gemini is busy right now. This usually clears within a minute."
            )
            return AnalysisUnavailableError(message, log_detail=f"{type(exc).__name__}: {exc}")
        return exc

    async def analyze_with_retry(
        self,
        video_path: str,
        on_stage: Optional[StageCallback] = None,
        attempts: int = 2,
        api_key: str | None = None,
    ) -> VideoAnalysis:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await self._analyze(video_path, on_stage=on_stage, api_key=api_key)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(2)
        assert last_error is not None
        raise self._as_domain_error(last_error)
