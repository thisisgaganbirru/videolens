import type { ServerAuthState, ServerAuthStatus } from "@/domain/ports";

/* The server's `auth` capability as the transport needs it (auth phase 2).
   Written by `FetchCapabilitiesGateway` every time a report arrives, read by
   `ApiClient` before it decides whether to send the bearer. In memory, per
   page load: a capability report is deployment shape, and the next load asks
   again. */
export class MemoryServerAuthStatus implements ServerAuthStatus {
  private state: ServerAuthState = "unknown";
  private readonly waiters = new Set<() => void>();

  current(): ServerAuthState {
    return this.state;
  }

  report(state: Exclude<ServerAuthState, "unknown">): void {
    this.state = state;
    for (const wake of [...this.waiters]) wake();
  }

  settled(maxMs: number): Promise<ServerAuthState> {
    if (this.state !== "unknown") return Promise.resolve(this.state);
    return new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        this.waiters.delete(done);
        resolve(this.state);
      };
      const timer = setTimeout(done, maxMs);
      this.waiters.add(done);
    });
  }
}
