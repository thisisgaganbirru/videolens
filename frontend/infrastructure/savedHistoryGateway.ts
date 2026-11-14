import type { SavedRunDetail, SavedRunPage, SavedRunSummary } from "@/domain/entities";
import { ApiError } from "@/domain/errors";
import type { SavedHistoryGateway } from "@/domain/ports";
import { UNREADABLE, type ApiClient } from "./apiClient";

/* Paid saved history (2026-11-14), `/api/history*`; contract in
   docs/backend/saved-history.md. Through `ApiClient`, so the bearer rides
   along. Tolerant on the way in: a malformed row is dropped rather than
   trusted, and every optional field may be absent (an older backend). The
   poster is the run's `thumbnail` data URL, kept only when it is one. */

function summaryOf(raw: unknown): SavedRunSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  if (typeof row.run_id !== "string" || typeof row.created_at !== "string") return null;
  const source = row.source && typeof row.source === "object" ? (row.source as SavedRunSummary["source"]) : null;
  return {
    run_id: row.run_id,
    created_at: row.created_at,
    title: typeof row.title === "string" ? row.title : null,
    summary_snippet: typeof row.summary_snippet === "string" ? row.summary_snippet : null,
    completeness: typeof row.completeness === "string" ? row.completeness : null,
    source,
    thumbnail: typeof row.thumbnail === "string" && row.thumbnail.startsWith("data:image/") ? row.thumbnail : null,
  };
}

export class FetchSavedHistoryGateway implements SavedHistoryGateway {
  constructor(private readonly client: ApiClient) {}

  async list(limit: number, cursor: string | null): Promise<SavedRunPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    const body = await this.client.json<Record<string, unknown> | null>(
      `/api/history?${query}`,
      {},
      "Could not load your saved runs"
    );
    if (!body || typeof body !== "object" || !Array.isArray(body.items)) throw new ApiError(UNREADABLE);
    return {
      saving: body.saving === true,
      expires_at: typeof body.expires_at === "string" ? body.expires_at : null,
      items: body.items.map(summaryOf).filter((item): item is SavedRunSummary => item !== null),
      next_cursor: typeof body.next_cursor === "string" && body.next_cursor ? body.next_cursor : null,
    };
  }

  async get(runId: string): Promise<SavedRunDetail> {
    const body = await this.client.json<Record<string, unknown> | null>(
      `/api/history/${encodeURIComponent(runId)}`,
      {},
      "Could not open that saved run"
    );
    const summary = summaryOf(body);
    const result = body?.result;
    if (!summary || !result || typeof result !== "object") throw new ApiError(UNREADABLE);
    return { ...summary, result: result as SavedRunDetail["result"] };
  }

  async remove(runId: string): Promise<void> {
    const res = await this.client.send(`/api/history/${encodeURIComponent(runId)}`, { method: "DELETE" });
    if (!res.ok) await this.client.reject(res, "Could not delete that saved run");
  }

  async removeAll(): Promise<number> {
    const res = await this.client.send("/api/history", { method: "DELETE" });
    if (!res.ok) await this.client.reject(res, "Could not delete your saved runs");
    const body = await res.json().catch(() => null);
    return typeof body?.deleted === "number" ? body.deleted : 0;
  }
}
