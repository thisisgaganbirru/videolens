import asyncio
import json
from typing import Awaitable, Callable, Optional

from google import genai
from google.genai import types

from .config import settings
from .models import VideoAnalysis

StageCallback = Callable[[str], Awaitable[None]]

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
- summary: a natural language summary of what the video covers
- transcript: the full spoken transcript
- transcript_segments: timestamped spoken segments with start_seconds, end_seconds, text, and optional speaker
- screen_text: the important on-screen text, in the order it appears
- screen_text_segments: timestamped visible-text segments with start_seconds, end_seconds, and text
- markdown: well-formatted markdown notes combining speech and visual context"""

_client: genai.Client | None = None


class GeminiConfigurationError(RuntimeError):
    pass


def _get_client() -> genai.Client:
    global _client
    if not settings.gemini_api_key.strip():
        raise GeminiConfigurationError(
            "Gemini API key is not configured. Add GEMINI_API_KEY to backend/.env "
            "and restart the backend."
        )
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def _wait_until_active(client: genai.Client, file_name: str, timeout: float = 120.0) -> None:
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


async def analyze_video(video_path: str, on_stage: Optional[StageCallback] = None) -> VideoAnalysis:
    if on_stage:
        await on_stage("uploading_to_gemini")
    client = _get_client()

    uploaded = await client.aio.files.upload(file=video_path)
    try:
        await _wait_until_active(client, uploaded.name)

        if on_stage:
            await on_stage("analyzing")
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
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


async def analyze_video_with_retry(
    video_path: str, on_stage: Optional[StageCallback] = None, attempts: int = 2
) -> VideoAnalysis:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await analyze_video(video_path, on_stage=on_stage)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(2)
    assert last_error is not None
    raise last_error
