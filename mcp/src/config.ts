/* Everything the server needs from its environment, read once at start.
   Credentials come only from `process.env`: never a tool argument (an agent
   could be talked into pasting one), never a file on disk. This mirrors how
   every widely used MCP server takes its secrets. */

export interface Config {
  /** Base URL of the VideoLens API, no trailing slash. */
  readonly apiUrl: string;
  /** Workspace API key (`vl_live_…`) from the account panel. Paid path:
   *  runs count against the plan's minutes and land in the library. */
  readonly apiKey: string | null;
  /** The caller's own Gemini key. Free path: the model bill is theirs, so
   *  nothing is metered and the shared daily cap does not apply. */
  readonly geminiApiKey: string | null;
  /** How long `analyze_video` waits before handing back the run id. */
  readonly defaultWaitSeconds: number;
}

export const DEFAULT_API_URL = "https://api.videolens.app";

export class ConfigError extends Error {}

export function readConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const apiKey = env.VIDEOLENS_API_KEY?.trim() || null;
  const geminiApiKey = env.GEMINI_API_KEY?.trim() || null;
  if (!apiKey && !geminiApiKey) {
    throw new ConfigError(
      "Set VIDEOLENS_API_KEY (a workspace key from the account panel) or " +
        "GEMINI_API_KEY (your own Gemini key, free path) in the MCP server's env.",
    );
  }
  if (apiKey && !apiKey.startsWith("vl_")) {
    throw new ConfigError("VIDEOLENS_API_KEY does not look like a VideoLens key (expected `vl_live_…`).");
  }
  const rawUrl = env.VIDEOLENS_API_URL?.trim() || DEFAULT_API_URL;
  let apiUrl: string;
  try {
    apiUrl = new URL(rawUrl).toString().replace(/\/+$/, "");
  } catch {
    throw new ConfigError(`VIDEOLENS_API_URL is not a URL: ${rawUrl}`);
  }
  const wait = Number(env.VIDEOLENS_WAIT_SECONDS ?? "");
  return {
    apiUrl,
    apiKey,
    geminiApiKey,
    defaultWaitSeconds: Number.isFinite(wait) && wait > 0 ? wait : 600,
  };
}
