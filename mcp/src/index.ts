#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { existsSync, statSync } from "node:fs";
import { extname, resolve } from "node:path";
import { z } from "zod";

import { ApiError, NetworkError, VideoLensClient } from "./client.js";
import { loadOrCreateClientId } from "./clientId.js";
import { ConfigError, readConfig } from "./config.js";
import { EXPORT_FORMATS, exportRun } from "./export.js";
import type { RunStatusResponse } from "./types.js";

const ACCEPTED_EXTENSIONS = new Set([".mp3", ".mp4", ".mov"]);

type ToolResult = { content: Array<{ type: "text"; text: string }>; isError?: boolean };

function text(body: string): ToolResult {
  return { content: [{ type: "text", text: body }] };
}

function json(value: unknown): ToolResult {
  return text(JSON.stringify(value, null, 2));
}

function failure(error: unknown): ToolResult {
  let message: string;
  if (error instanceof ApiError) {
    message =
      error.status === 401 || error.status === 403
        ? `Not authorized: ${error.message} Check the credential in the MCP server's env.`
        : error.status === 429
          ? `Rate limited: ${error.message}`
          : error.message;
  } else if (error instanceof NetworkError) {
    message = error.message;
  } else if (error instanceof Error) {
    message = error.message;
  } else {
    message = String(error);
  }
  return { content: [{ type: "text", text: message }], isError: true };
}

/** What the agent gets back for a run: the stored result, with the status
 *  and any caveat up front so a partial answer is never mistaken for a
 *  complete one. */
function describeRun(run: RunStatusResponse, note?: string): ToolResult {
  const header: Record<string, unknown> = { run_id: run.run_id, status: run.status };
  if (run.stage) header.stage = run.stage;
  if (run.error) header.error = run.error;
  if (run.completeness === "captions_only") {
    header.caveat =
      "Analyzed from the published captions only: the media could not be downloaded, so on-screen text is missing.";
  }
  if (note) header.note = note;
  if (run.source_metadata) header.source = run.source_metadata;
  if (run.result) header.result = run.result;
  return json(header);
}

async function main(): Promise<void> {
  const config = readConfig();
  const client = new VideoLensClient(config, config.apiKey ? "" : loadOrCreateClientId());

  const server = new McpServer({ name: "videolens", version: "0.1.0" });

  server.registerTool(
    "analyze_video",
    {
      title: "Analyze a video",
      description:
        "Analyze a short video or audio file with VideoLens: returns a transcript with timestamps, " +
        "on-screen text, a summary, and markdown notes. Give either a public URL (YouTube, Instagram, " +
        "TikTok, Facebook, X, or a direct media link) or a local .mp3/.mp4/.mov path. Blocks while the " +
        "run processes (default up to 10 minutes); if the wait runs out you get the run_id and can call " +
        `get_run later. Credential in use: ${client.describeAuth()}.`,
      inputSchema: {
        url: z.string().url().optional().describe("Public URL of the video to analyze."),
        file_path: z.string().optional().describe("Absolute or cwd-relative path to a local .mp3/.mp4/.mov file."),
        wait_seconds: z
          .number()
          .int()
          .min(0)
          .max(3600)
          .optional()
          .describe(`Seconds to wait for the result before returning the run_id. Default ${config.defaultWaitSeconds}.`),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    },
    async ({ url, file_path, wait_seconds }, extra) => {
      if (!url === !file_path) return failure(new Error("Give exactly one of `url` or `file_path`."));
      try {
        let created;
        if (url) {
          created = await client.createRunFromUrl(url);
        } else {
          const path = resolve(file_path!);
          if (!existsSync(path) || !statSync(path).isFile()) return failure(new Error(`No file at ${path}.`));
          if (!ACCEPTED_EXTENSIONS.has(extname(path).toLowerCase())) {
            return failure(new Error("Only .mp3, .mp4 and .mov files are supported."));
          }
          created = await client.createRunFromFile(path);
        }
        const budget = wait_seconds ?? config.defaultWaitSeconds;
        const run = await client.waitForRun(created.run_id, budget, (stage, status) => {
          void extra.sendNotification({
            method: "notifications/message",
            params: { level: "info", data: `run ${created.run_id}: ${stage ?? status}` },
          });
        });
        if (run.status === "queued" || run.status === "processing") {
          return describeRun(
            run,
            `Still ${run.status} after ${budget}s. Call get_run with this run_id to collect the result.`,
          );
        }
        if (run.status === "failed") return { ...describeRun(run), isError: true };
        return describeRun(run);
      } catch (error) {
        return failure(error);
      }
    },
  );

  server.registerTool(
    "get_run",
    {
      title: "Get a run",
      description:
        "Fetch one analysis by run_id: its status, current stage while processing, and the full result " +
        "once complete. Use it to collect a run analyze_video handed back unfinished, or to reopen anything " +
        "from list_recent_runs or search_library.",
      inputSchema: { run_id: z.string().min(1).describe("The run_id returned by analyze_video or a listing.") },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ run_id }) => {
      try {
        return describeRun(await client.getRun(run_id));
      } catch (error) {
        return failure(error);
      }
    },
  );

  server.registerTool(
    "list_recent_runs",
    {
      title: "List recent runs",
      description:
        "The caller's most recent analyses, newest first (at most 20): run_id, status, title, created_at. " +
        "For anything older or to search by content, use search_library.",
      inputSchema: {
        limit: z.number().int().min(1).max(20).optional().describe("How many to return. Default 20."),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ limit }) => {
      try {
        const { runs } = await client.listRuns();
        return json({ runs: runs.slice(0, limit ?? 20) });
      } catch (error) {
        return failure(error);
      }
    },
  );

  server.registerTool(
    "search_library",
    {
      title: "Search the library",
      description:
        "Search everything the caller has ever analyzed. With a workspace API key this is full-text search " +
        "over titles, summaries, transcripts and on-screen text of every stored run; anonymously it is a " +
        "title match over recent history. Returns run_id, title, summary, platform, source_url, duration " +
        "and created_at per hit - call get_run for the full result.",
      inputSchema: {
        query: z.string().max(200).optional().describe("Words to search for. Empty lists newest first."),
        platform: z
          .string()
          .max(64)
          .optional()
          .describe("Restrict to one source: youtube, instagram, tiktok, facebook, twitter, or upload."),
        since: z.string().datetime({ offset: true }).optional().describe("ISO 8601: only runs created at or after."),
        until: z.string().datetime({ offset: true }).optional().describe("ISO 8601: only runs created before."),
        limit: z.number().int().min(1).max(50).optional().describe("Page size. Default 20."),
        offset: z.number().int().min(0).optional().describe("Page offset for the next page."),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async (args) => {
      try {
        return json(await client.searchLibrary(args));
      } catch (error) {
        return failure(error);
      }
    },
  );

  server.registerTool(
    "export_run",
    {
      title: "Export a run",
      description:
        "Render a finished run as a file body: `markdown` (the notes), `json` (the whole run), " +
        "`transcript` (timestamped plain text), `srt` or `vtt` (subtitles), or `screen_text` " +
        "(timestamped on-screen text). Nothing is recomputed - this is free and instant.",
      inputSchema: {
        run_id: z.string().min(1),
        format: z.enum(EXPORT_FORMATS).describe("Which rendering to return."),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async ({ run_id, format }) => {
      try {
        const exported = exportRun(await client.getRun(run_id), format);
        return {
          content: [
            { type: "text", text: `${run_id}.${exported.extension} (${exported.mediaType})` },
            { type: "text", text: exported.body },
          ],
        };
      } catch (error) {
        return failure(error);
      }
    },
  );

  server.registerTool(
    "account_status",
    {
      title: "Account status",
      description:
        "Who the server is acting as and what is left: plan, minutes used and remaining this period, " +
        "the longest video the plan accepts, and whether the library and API access are on.",
      inputSchema: {},
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    async () => {
      try {
        return json(await client.account());
      } catch (error) {
        return failure(error);
      }
    },
  );

  await server.connect(new StdioServerTransport());
}

main().catch((error: unknown) => {
  // stdout is the protocol channel; anything for a human goes to stderr.
  const message = error instanceof ConfigError ? error.message : error instanceof Error ? error.stack ?? error.message : String(error);
  process.stderr.write(`videolens-mcp: ${message}\n`);
  process.exit(1);
});
