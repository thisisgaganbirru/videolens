import type { AccountDeletionOutcome, AccountResponse, ApiKeyCreated, ApiKeyListResponse } from "@/domain/entities";
import type { AccountGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";

/* `GET|DELETE /api/me`, `GET|POST /api/keys`, `DELETE /api/keys/{id}` (contract in
   docs/backend/auth.md). Sent through `ApiClient`, so the bearer token rides
   along whenever someone is signed in. Signed out, `/api/me` answers 401 and
   the hooks never ask; `/api/keys` refuses anything but a signed-in person.
   Billing has its own gateway (billingGateway.ts). */
export class FetchAccountGateway implements AccountGateway {
  constructor(private readonly client: ApiClient) {}

  fetchAccount(): Promise<AccountResponse> {
    return this.client.json<AccountResponse>("/api/me", {}, "Could not load your account");
  }

  listKeys(): Promise<ApiKeyListResponse> {
    return this.client.json<ApiKeyListResponse>("/api/keys", {}, "Could not load API keys");
  }

  createKey(name: string): Promise<ApiKeyCreated> {
    return this.client.jsonBody<ApiKeyCreated>("/api/keys", "POST", { name }, "Could not create the API key");
  }

  async revokeKey(keyId: string): Promise<void> {
    const res = await this.client.send(`/api/keys/${encodeURIComponent(keyId)}`, { method: "DELETE" });
    if (!res.ok) await this.client.reject(res, "Could not revoke the API key");
  }

  /* 200 `{status: "pending_deletion", purge_at}` since 2026-11-14 (the
     30-day hold); an older backend's 204 has no body and removed the
     account at once, which `purgeAt: null` reports. */
  async deleteAccount(): Promise<AccountDeletionOutcome> {
    const res = await this.client.send("/api/me", { method: "DELETE" });
    if (!res.ok) await this.client.reject(res, "Could not delete your account");
    if (res.status === 204) return { purgeAt: null };
    const body = await res.json().catch(() => null);
    return { purgeAt: typeof body?.purge_at === "string" ? body.purge_at : null };
  }

  /** `POST /api/me/restore`: true when a held account was restored. */
  async restoreAccount(): Promise<boolean> {
    const res = await this.client.send("/api/me/restore", { method: "POST" });
    if (!res.ok) await this.client.reject(res, "Could not restore your account");
    const body = await res.json().catch(() => null);
    return body?.restored === true;
  }
}
