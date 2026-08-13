import { VideoLensApiError, VideoLensClient, type RunStatusResponse } from "./client.js";

const POLL_INTERVAL_MS = 5_000;
// Matches the backend's WORKER_JOB_TIMEOUT_SECONDS default (600s) — no point
// waiting longer than the worker itself would before giving up on a job.
const TIMEOUT_MS = Number(process.env.VIDEOLENS_POLL_TIMEOUT_SECONDS ?? 600) * 1_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function pollUntilFinished(client: VideoLensClient, runId: string): Promise<RunStatusResponse> {
  const deadline = Date.now() + TIMEOUT_MS;

  while (Date.now() < deadline) {
    const run = await client.getRun(runId);
    if (run.status === "complete" || run.status === "failed") {
      return run;
    }
    await sleep(POLL_INTERVAL_MS);
  }

  throw new VideoLensApiError(
    `Run ${runId} did not finish within ${TIMEOUT_MS / 1000}s. It may still complete — check with list_recent_runs.`,
  );
}
