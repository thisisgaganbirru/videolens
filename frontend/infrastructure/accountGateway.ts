import type { AccountResponse, ApiKeyCreated, ApiKeyListResponse, Plan } from "@/domain/entities";
import type { AccountGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";

export class FetchAccountGateway implements AccountGateway {
  constructor(private readonly client: ApiClient) {}

  async fetchAccount(): Promise<AccountResponse> {
    return this.client.json<AccountResponse>("/api/me", {}, "Could not load your account");
  }

  async listKeys(): Promise<ApiKeyListResponse> {
    return this.client.json<ApiKeyListResponse>("/api/keys", {}, "Could not load API keys");
  }

  async createKey(name: string): Promise<ApiKeyCreated> {
    return this.client.jsonBody<ApiKeyCreated>("/api/keys", "POST", { name }, "Could not create the API key");
  }

  async revokeKey(keyId: string): Promise<void> {
    const res = await this.client.send(`/api/keys/${encodeURIComponent(keyId)}`, { method: "DELETE" });
    if (!res.ok) await this.client.reject(res, "Could not revoke the API key");
  }

  async startCheckout(plan: Plan): Promise<string> {
    const body = await this.client.jsonBody<{ url: string }>(
      "/api/billing/checkout",
      "POST",
      { plan },
      "Could not start checkout",
    );
    return body.url;
  }

  async openBillingPortal(): Promise<string> {
    const body = await this.client.json<{ url: string }>(
      "/api/billing/portal",
      { method: "POST" },
      "Could not open billing",
    );
    return body.url;
  }
}
