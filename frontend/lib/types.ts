export type RunStatus = "queued" | "processing" | "complete" | "failed";

export interface TranscriptSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
  speaker?: string | null;
}

export interface ScreenTextSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
}

export interface VideoAnalysis {
  title: string;
  summary: string;
  transcript: string;
  transcript_segments?: TranscriptSegment[];
  screen_text: string;
  screen_text_segments?: ScreenTextSegment[];
  markdown: string;
}

export interface RunCreateResponse {
  run_id: string;
  status: RunStatus;
}

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  stage: string | null;
  result: VideoAnalysis | null;
  error: string | null;
}
