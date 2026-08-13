import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const STATE_DIR = join(homedir(), ".videolens");
const CLIENT_ID_FILE = join(STATE_DIR, "client_id");

/**
 * Stable per-machine identifier, persisted locally. Not a secret — it only
 * scopes which runs `list_recent_runs` sees, same role X-Client-ID plays for
 * the web app's localStorage-backed identity. Created once, reused after.
 */
export function getOrCreateClientId(): string {
  try {
    const existing = readFileSync(CLIENT_ID_FILE, "utf-8").trim();
    if (existing) return existing;
  } catch {
    // File doesn't exist yet — fall through to create it.
  }

  const id = `mcp:${randomUUID()}`;
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(CLIENT_ID_FILE, id, "utf-8");
  return id;
}
