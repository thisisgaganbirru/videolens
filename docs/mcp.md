# MCP server

Lets terminal AI agents (Claude Code, Cursor, Codex, Antigravity, ...) call VideoLens directly instead of going through the web UI.

**Files**
- `mcp/src/index.ts` — server entry; registers `analyze_video` and `list_recent_runs`, reads `GEMINI_API_KEY`/`VIDEOLENS_API_BASE_URL` from `process.env`, connects over stdio.
- `mcp/src/client.ts` — `VideoLensClient`, a thin REST client over `POST /api/runs` / `GET /api/runs` / `GET /api/runs/{run_id}` — the same endpoints `frontend/infrastructure/runsGateway.ts` calls, different transport.
- `mcp/src/poll.ts` — `pollUntilFinished`, polls a run every 5s up to `VIDEOLENS_POLL_TIMEOUT_SECONDS` (default 600s, matching the backend's `WORKER_JOB_TIMEOUT_SECONDS` default).
- `mcp/src/clientId.ts` — `getOrCreateClientId`, persists a random `mcp:<uuid>` to `~/.videolens/client_id` on first run.
- `.mcp.json` (repo root) — auto-registers this repo's local build for contributors; references `${GEMINI_API_KEY}`, never a literal value.

**Why BYOK is mandatory here, unlike the web app's optional BYOK panel**: agent-driven traffic can loop or batch far more easily than a human clicking upload once, so there's no shared-quota fallback — every `analyze_video` call requires the caller's own Gemini key. See the "MCP server" section in `CLAUDE.md` for the full reasoning.

**Credential handling**: `GEMINI_API_KEY` is read once from `process.env` at server startup — supplied via the calling MCP client's `env` config block, never as a tool-call argument (which would put it in the model's context on every call) and never written to any file. This matches how every major MCP server (GitHub's, Slack's, Sentry's, Anthropic's own reference servers) handles credentials — it's the protocol's designated mechanism, not a project-specific choice.

**`~/.videolens/client_id` is not a secret**: it only scopes what `list_recent_runs` returns, the same non-authorizing role `X-Client-ID` plays for the web app's `localStorage`-backed identity. Stored in plaintext deliberately — hashing an identifier that isn't protecting anything adds no security value.

**Known issues**:
- Not published to npm yet — deliberately held, not just unfinished. `videolens-mcp` is confirmed available on the registry, but publishing under a name tied to the still-unresolved product branding (see `research/council/council-transcript-20260810.md` — "Jotlens" is the provisional leading candidate, unverified) risks an orphaned/renamed package later. Decision: wait for the real name, keep `mcp/README.md`'s local-build instructions as the only path until then. Revisit once branding is locked.
- `analyze_video` uploads local files by reading them into memory (`readFile` + `Blob`) before sending — fine for the existing `MAX_FILE_SIZE_MB` ceiling, would need streaming if that limit ever grows substantially.
- Sleep-on-idle caveat noted in `DEPLOYMENT.md`: if pointed at the Railway `dev` backend, the `videolens-worker` service's scale-to-zero behavior is unverified for non-HTTP (arq) wake-up — an `analyze_video` call could stall waiting for a sleeping worker to wake. Untested until a real deploy happens.

**Tests**: none yet — no test harness exists in `mcp/` currently.
