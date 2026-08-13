# videolens-mcp

MCP server exposing VideoLens AI's video analysis to terminal AI agents —
Claude Code, Cursor, Codex, Antigravity, or any MCP-speaking client.

Not yet published to npm. Until it is, build and run it locally:

```bash
cd mcp
npm install
npm run build
```

## Tools

- **`analyze_video(file_path?, url?)`** — upload a local file or submit a
  public media URL, blocks until the analysis finishes, returns
  `{ title, summary, transcript, screen_text, markdown }`. Exactly one of
  `file_path` or `url` is required.
- **`list_recent_runs()`** — lists this machine's recent runs, newest first.
  Scoped to a stable local client ID (`~/.videolens/client_id`), not an
  account — only runs created from this machine are visible.

## Configuration

Every tool call requires your own Gemini API key — this server does not use
VideoLens's shared quota. Get one from
[Google AI Studio](https://aistudio.google.com/apikey), then add this server
to your agent's MCP config with the key in its `env` block (never as a tool
argument — it's read once from the process environment, same as any other
MCP server's credential):

```json
{
  "mcpServers": {
    "videolens": {
      "command": "node",
      "args": ["/absolute/path/to/videolens/mcp/dist/index.js"],
      "env": {
        "GEMINI_API_KEY": "your-gemini-api-key",
        "VIDEOLENS_API_BASE_URL": "https://your-videolens-backend.example.com"
      }
    }
  }
}
```

`VIDEOLENS_API_BASE_URL` defaults to `http://localhost:8000` (a local
`backend/` dev server) if omitted — point it at a deployed backend
(see `DEPLOYMENT.md`) to use a hosted instance instead.

This repo's own root `.mcp.json` auto-registers the local build (`node
mcp/dist/index.js`) for anyone working in this repo — you still need to
supply your own `GEMINI_API_KEY` in your personal MCP client settings, since
that value is never committed here.

## Design notes

- No `.env` file anywhere in this server — the Gemini key lives only in
  `process.env`, injected by the calling MCP client. See the credential
  handling note in `CONTRIBUTING.md`/`CLAUDE.md` if you're touching this.
- The local client ID is not a secret; it only scopes `list_recent_runs`,
  the same role `X-Client-ID` plays for the web app's `localStorage`-backed
  identity. Nothing here is hashed because nothing here needs to be.
- BYOK is mandatory (not optional) specifically for agent traffic — see
  `mem/20260813-mcp-server-design.md` for why the shared-quota fallback
  used by the web app's BYOK panel was deliberately not carried over here.
