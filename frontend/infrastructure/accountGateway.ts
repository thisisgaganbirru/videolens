import type { AccountResponse, ApiKeyCreated, ApiKeyListResponse } from "@/domain/entities";
import type { AccountGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";

/* `GET /api/me`, `GET|POST /api/keys`, `DELETE /api/keys/{id}` (contract in
   docs/backend/auth.md). Sent through `ApiClient`, so the bearer token rides
   along whenever someone is signed in. Signed out, `/api/me` answers 401 and
   the hooks never ask; `/api/keys` refuses anything but a signed-in person.
   No billing methods: the paid tier is deferred. */
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
}
