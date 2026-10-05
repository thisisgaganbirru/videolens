import type { LibraryQuery, LibraryResponse } from "@/domain/entities";
import type { LibraryGateway } from "@/domain/ports";
import type { ApiClient } from "./apiClient";

export class FetchLibraryGateway implements LibraryGateway {
  constructor(private readonly client: ApiClient) {}

  async search(params: LibraryQuery): Promise<LibraryResponse> {
    const search = new URLSearchParams();
    if (params.query) search.set("query", params.query);
    if (params.platform) search.set("platform", params.platform);
    if (params.since) search.set("since", params.since);
    if (params.until) search.set("until", params.until);
    if (params.limit) search.set("limit", String(params.limit));
    if (params.offset) search.set("offset", String(params.offset));
    const qs = search.toString();
    return this.client.json<LibraryResponse>(
      `/api/library${qs ? `?${qs}` : ""}`,
      {},
      "Could not search your library",
    );
  }
}
