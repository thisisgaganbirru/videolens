import type { RunStatusResponse, ScreenTextSegment, TranscriptSegment, VideoAnalysis } from "./types.js";

/* Turns a finished run into the file an agent was going to write anyway.
   Everything here is derived from the stored result - nothing calls the
   model again, so an export is free and instant. */

export const EXPORT_FORMATS = ["markdown", "json", "transcript", "srt", "vtt", "screen_text"] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

export interface Exported {
  format: ExportFormat;
  /** A sensible file extension for the agent to save under. */
  extension: string;
  mediaType: string;
  body: string;
}

export function exportRun(run: RunStatusResponse, format: ExportFormat): Exported {
  const result = run.result;
  if (!result) {
    throw new Error(
      run.status === "failed"
        ? `Run ${run.run_id} failed: ${run.error ?? "no result was stored."}`
        : `Run ${run.run_id} is still ${run.status}; there is nothing to export yet.`,
    );
  }
  switch (format) {
    case "markdown":
      return { format, extension: "md", mediaType: "text/markdown", body: withCaveat(result.markdown, run) };
    case "json":
      return { format, extension: "json", mediaType: "application/json", body: JSON.stringify(run, null, 2) };
    case "transcript":
      return { format, extension: "txt", mediaType: "text/plain", body: plainTranscript(result) };
    case "srt":
      return { format, extension: "srt", mediaType: "application/x-subrip", body: toSrt(segments(result)) };
    case "vtt":
      return { format, extension: "vtt", mediaType: "text/vtt", body: toVtt(segments(result)) };
    case "screen_text":
      return { format, extension: "txt", mediaType: "text/plain", body: screenText(result) };
  }
}

function withCaveat(markdown: string, run: RunStatusResponse): string {
  if (run.completeness !== "captions_only") return markdown;
  return (
    "> Analyzed from the published captions only: the media itself could not " +
    "be downloaded, so on-screen text and anything not spoken is missing.\n\n" +
    markdown
  );
}

function segments(result: VideoAnalysis): TranscriptSegment[] {
  return result.transcript_segments ?? [];
}

function plainTranscript(result: VideoAnalysis): string {
  const segs = segments(result);
  if (segs.length === 0) return result.transcript;
  return segs
    .map((seg) => {
      const speaker = seg.speaker ? `${seg.speaker}: ` : "";
      return `[${clock(seg.start_seconds)}] ${speaker}${seg.text}`;
    })
    .join("\n");
}

function screenText(result: VideoAnalysis): string {
  const segs: ScreenTextSegment[] = result.screen_text_segments ?? [];
  if (segs.length === 0) return result.screen_text;
  return segs.map((seg) => `[${clock(seg.start_seconds)}] ${seg.text}`).join("\n");
}

export function toSrt(segs: TranscriptSegment[]): string {
  return segs
    .map((seg, index) => {
      const speaker = seg.speaker ? `${seg.speaker}: ` : "";
      return `${index + 1}\n${stamp(seg.start_seconds, ",")} --> ${stamp(seg.end_seconds, ",")}\n${speaker}${seg.text}\n`;
    })
    .join("\n");
}

export function toVtt(segs: TranscriptSegment[]): string {
  const cues = segs.map((seg) => {
    const speaker = seg.speaker ? `<v ${seg.speaker}>` : "";
    return `${stamp(seg.start_seconds, ".")} --> ${stamp(seg.end_seconds, ".")}\n${speaker}${seg.text}\n`;
  });
  return ["WEBVTT", "", ...cues].join("\n");
}

/** `HH:MM:SS,mmm` (SRT) or `HH:MM:SS.mmm` (WebVTT). */
export function stamp(seconds: number, separator: "," | "."): string {
  const total = Math.max(0, seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = Math.floor(total % 60);
  const millis = Math.round((total - Math.floor(total)) * 1000);
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)}${separator}${pad(millis, 3)}`;
}

/** `M:SS` or `H:MM:SS`, for a transcript a person reads. */
export function clock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mm = hours ? String(minutes).padStart(2, "0") : String(minutes);
  return `${hours ? `${hours}:` : ""}${mm}:${String(secs).padStart(2, "0")}`;
}
