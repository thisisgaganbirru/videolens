#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { VideoLensClient } from "./client.js";
import { getOrCreateClientId } from "./clientId.js";
import { pollUntilFinished } from "./poll.js";

const GEMINI_API_KEY = process.env.GEMINI_API_KEY?.trim();
if (!GEMINI_API_KEY) {
  console.error(
    "videolens-mcp: GEMINI_API_KEY is required. Set it in this server's " +
      "\"env\" block in your MCP client config (Claude Code, Cursor, etc.) — " +
      "get a key from https://aistudio.google.com/apikey.",
  );
  process.exit(1);
}

const baseUrl = (process.env.VIDEOLENS_API_BASE_URL?.trim() || "http://localhost:8000").replace(/\/$/, "");
const clientId = getOrCreateClientId();
const client = new VideoLensClient(baseUrl, GEMINI_API_KEY, clientId);

const server = new McpServer({ name: "videolens", version: "0.1.0" });

server.registerTool(
  "analyze_video",
  {
    title: "Analyze a video",
    description:
      "Upload a local video/audio file or submit a public media URL to VideoLens AI and get back a transcript, " +
      "on-screen text, a summary, and formatted markdown notes. Blocks until the analysis finishes (or fails).",
    inputSchema: {
      file_path: z.string().optional().describe("Absolute path to a local MP3, MP4, or MOV file."),
      url: z.string().optional().describe("A public HTTP(S) media URL (YouTube, TikTok, Instagram, etc.)."),
    },
  },
  async ({ file_path, url }) => {
    if (!file_path && !url) {
      return errorResult("Provide either file_path or url.");
    }
    if (file_path && url) {
      return errorResult("Provide only one of file_path or url, not both.");
    }

    try {
      const created = await client.createRun({ filePath: file_path, url });
      const finished = await pollUntilFinished(client, created.run_id);

      if (finished.status === "failed") {
        return errorResult(finished.error || "The run failed with no error detail.");
      }

      return {
        content: [{ type: "text", text: JSON.stringify(finished.result, null, 2) }],
      };
    } catch (err) {
      return errorResult(err instanceof Error ? err.message : String(err));
    }
  },
);

server.registerTool(
  "list_recent_runs",
  {
    title: "List recent VideoLens runs",
    description:
      "List this machine's recent VideoLens analysis runs (newest first). Scoped to a stable local client ID, " +
      "not an account — only runs created from this machine are visible.",
    inputSchema: {},
  },
  async () => {
    try {
      const runs = await client.listRuns();
      return { content: [{ type: "text", text: JSON.stringify(runs, null, 2) }] };
    } catch (err) {
      return errorResult(err instanceof Error ? err.message : String(err));
    }
  },
);

function errorResult(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true as const };
}

const transport = new StdioServerTransport();
await server.connect(transport);
