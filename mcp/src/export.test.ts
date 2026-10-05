import assert from "node:assert/strict";
import { test } from "node:test";

import { clock, exportRun, stamp, toSrt, toVtt } from "./export.js";
import type { RunStatusResponse } from "./types.js";

const run: RunStatusResponse = {
  run_id: "run-1",
  status: "complete",
  stage: null,
  error: null,
  completeness: "full",
  result: {
    title: "Sourdough basics",
    summary: "How to start a levain.",
    transcript: "Mix flour and water.",
    transcript_segments: [
      { start_seconds: 0, end_seconds: 2.5, text: "Mix flour and water.", speaker: "Host" },
      { start_seconds: 62.25, end_seconds: 65, text: "Wait a day." },
    ],
    screen_text: "STEP 1",
    screen_text_segments: [{ start_seconds: 1, end_seconds: 3, text: "STEP 1" }],
    markdown: "# Sourdough basics\n\nNotes.",
  },
};

test("timestamps render in subtitle and clock forms", () => {
  assert.equal(stamp(3661.5, ","), "01:01:01,500");
  assert.equal(stamp(0, "."), "00:00:00.000");
  assert.equal(clock(62), "1:02");
  assert.equal(clock(3661), "1:01:01");
});

test("srt and vtt carry every segment", () => {
  const segs = run.result!.transcript_segments!;
  const srt = toSrt(segs);
  assert.match(srt, /^1\n00:00:00,000 --> 00:00:02,500\nHost: Mix flour and water\.\n/);
  assert.match(srt, /\n2\n00:01:02,250 --> 00:01:05,000\nWait a day\.\n/);
  const vtt = toVtt(segs);
  assert.ok(vtt.startsWith("WEBVTT\n\n"));
  assert.match(vtt, /<v Host>Mix flour and water\./);
});

test("transcript and screen text fall back to the flat strings", () => {
  assert.equal(exportRun(run, "transcript").body, "[0:00] Host: Mix flour and water.\n[1:02] Wait a day.");
  assert.equal(exportRun(run, "screen_text").body, "[0:01] STEP 1");
  const flat = { ...run, result: { ...run.result!, transcript_segments: [], screen_text_segments: [] } };
  assert.equal(exportRun(flat, "transcript").body, "Mix flour and water.");
  assert.equal(exportRun(flat, "screen_text").body, "STEP 1");
});

test("markdown carries the captions-only caveat", () => {
  assert.equal(exportRun(run, "markdown").body, "# Sourdough basics\n\nNotes.");
  const captions = { ...run, completeness: "captions_only" as const };
  assert.match(exportRun(captions, "markdown").body, /^> Analyzed from the published captions only/);
});

test("an unfinished or failed run refuses to export", () => {
  assert.throws(() => exportRun({ ...run, status: "processing", result: null }, "json"), /still processing/);
  assert.throws(
    () => exportRun({ ...run, status: "failed", result: null, error: "Too long." }, "json"),
    /failed: Too long\./,
  );
});
