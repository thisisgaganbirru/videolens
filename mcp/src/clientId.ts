import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/* The anonymous path's identity: the same role `X-Client-ID` plays for the
   web app, where it lives in `localStorage`. It scopes which runs
   `list_recent_runs` can see and nothing more - it is not a secret and it
   authorizes no quota, so a plain dotfile is the right home for it. Created
   once, reused forever, so an agent's history survives restarts. */

const CLIENT_ID_PATTERN = /^[A-Za-z0-9._:-]{16,128}$/;

export function clientIdPath(home: string = homedir()): string {
  return join(home, ".videolens", "client_id");
}

export function loadOrCreateClientId(path: string = clientIdPath()): string {
  try {
    const existing = readFileSync(path, "utf8").trim();
    if (CLIENT_ID_PATTERN.test(existing)) return existing;
  } catch {
    // Missing or unreadable: fall through and mint one.
  }
  const fresh = `mcp-${randomUUID()}`;
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, `${fresh}\n`, { mode: 0o600 });
  return fresh;
}
