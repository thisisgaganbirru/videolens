# VideoLens MCP server

Lets terminal AI agents (Claude Code, Cursor, Codex, Antigravity, Claude
Desktop, or any MCP client) analyze videos with VideoLens and search
everything they have analyzed, without going through the web UI.

It is a thin REST client over the same `backend/` API the web app uses. It
adds no backend surface and shares no code with it: `src/client.ts` plays the
role `frontend/infrastructure/runsGateway.ts` plays for the browser, over
stdio instead of a page.

## Tools

| Tool | What it does |
|---|---|
| `analyze_video({ url?, file_path?, wait_seconds? })` | Submit a public URL or a local `.mp3`/`.mp4`/`.mov` and block until the result is in (default 10 min). Returns the transcript with timestamps, on-screen text, summary and markdown notes. If the wait runs out you get the `run_id` back to collect later. |
| `get_run({ run_id })` | One run's status, stage, and full result. |
| `list_recent_runs({ limit? })` | Your last 20 analyses, newest first. |
| `search_library({ query?, platform?, since?, until?, limit?, offset? })` | Full-text search across every run your workspace has stored (titles, summaries, transcripts, on-screen text). Anonymously it is a title match over recent history. |
| `export_run({ run_id, format })` | A finished run as `markdown`, `json`, `transcript`, `srt`, `vtt` or `screen_text`. Free and instant, nothing is recomputed. |
| `account_status()` | Which credential is in use, the plan, minutes used and remaining, and the longest video the plan accepts. |

## Credentials

Exactly one of these must be in the server's `env`. Credentials are read
once from `process.env` at start and are never a tool argument or a file on
disk, so an agent cannot be talked into pasting one somewhere.

- **`VIDEOLENS_API_KEY`** (`vl_live_…`), issued from the web app's account
  panel on a plan with API access. Runs count against the workspace's
  minutes and land in its library, which is what makes `search_library`
  useful.
- **`GEMINI_API_KEY`**, your own Gemini key. The free path: the model bill is
  yours, so nothing is metered and the shared daily cap does not apply.
  Unlike the web app there is no shared-quota fallback here, because agent
  traffic loops and batches far more easily than a person clicking upload.
  On this path the server keeps a non-secret client id in
  `~/.videolens/client_id` so your history survives restarts; it scopes what
  `list_recent_runs` can see and authorizes nothing.

Setting both is allowed: the API key identifies the workspace and the
Gemini key pays for the model, so those runs are stored but not metered.

Optional:

- `VIDEOLENS_API_URL`: the API to talk to. Defaults to the hosted service;
  set `http://localhost:8000` against a local backend.
- `VIDEOLENS_WAIT_SECONDS`: default wait for `analyze_video` (600).

## Setup

Not on npm yet, so point your client at a local build:

```bash
cd mcp
npm install
npm run build        # emits dist/index.js
```

Claude Code, from this repository, needs nothing more: the root `.mcp.json`
registers the server and reads `GEMINI_API_KEY` / `VIDEOLENS_API_KEY` from
your shell. Elsewhere, add it to your client's MCP config:

```json
{
  "mcpServers": {
    "videolens": {
      "command": "node",
      "args": ["/absolute/path/to/videolens/mcp/dist/index.js"],
      "env": {
        "VIDEOLENS_API_KEY": "vl_live_..."
      }
    }
  }
}
```

Claude Code can also do it from the CLI:

```bash
claude mcp add videolens -e VIDEOLENS_API_KEY=vl_live_... -- node /absolute/path/to/videolens/mcp/dist/index.js
```

Once published the `command` becomes `npx` with args `["-y", "@videolens/mcp"]`.

## Development

```bash
npm run typecheck    # tsc --noEmit
npm test             # builds, then runs the export-format tests with node --test
```

Smoke test by hand against a local backend (`uvicorn app.main:app` in
`backend/`): run the server with `VIDEOLENS_API_URL=http://localhost:8000`
and `GEMINI_API_KEY` set, and drive it with any MCP client. stdout is the
protocol channel; anything meant for a person goes to stderr.

## Layout

- `src/index.ts`: the server and its tool registrations.
- `src/client.ts`: the REST client and its two error types (`NetworkError`
  for a request that never got an answer, `ApiError` for a refusal, carrying
  the server's own sentence).
- `src/export.ts`: the export renderers (SRT/VTT timestamps, timestamped
  transcript, captions-only caveat).
- `src/config.ts`: environment reading and the startup checks.
- `src/clientId.ts`: the `~/.videolens/client_id` dotfile.
- `src/types.ts`: wire shapes mirroring `backend/app/interface/api/schemas.py`.
