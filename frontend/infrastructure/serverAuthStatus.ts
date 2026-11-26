import type { ServerAuthState, ServerAuthStatus } from "@/domain/ports";

/* The server's `auth` capability as the transport needs it (auth phase 2).
   Written by `FetchCapabilitiesGateway` every time a report arrives, read by
   `ApiClient` before it decides whether to send the bearer. In memory, per
   page load: a capability report is deployment shape, and the next load asks
   again.

   2026-11-21: the report used to be read once per load, so a failed read (a
   5xx during a deploy, an unreadable body) or a `degraded` one (the sign-in
   keys briefly unreachable) left every signed-in request waiting its full
   8 s and failing until a reload; on Android nothing refocuses to retry. Now
   a caller that needs a decisive answer asks for one (`requestReport`), and
   while anyone is waiting the read is repeated, spaced, until the answer is
   decisive or the wait ends. */

/** The shortest gap between two reads started from here. */
const MIN_READ_INTERVAL_MS = 5000;

/** `ok` or `off`: the transport knows what to send. */
function isDecisive(state: ServerAuthState): boolean {
  return state === "ok" || state === "off";
}

export class MemoryServerAuthStatus implements ServerAuthStatus {
  private state: ServerAuthState = "unknown";
  private readonly waiters = new Set<() => void>();
  private reader: (() => Promise<unknown>) | null = null;
  private reading = false;
  private lastReadAt = Number.NEGATIVE_INFINITY;
  private later: ReturnType<typeof setTimeout> | null = null;

  current(): ServerAuthState {
    return this.state;
  }

  report(state: Exclude<ServerAuthState, "unknown">): void {
    this.state = state;
    /* Only a decisive answer ends a wait; a `degraded` one keeps it going
       until the next read or the deadline. */
    if (isDecisive(state)) for (const wake of [...this.waiters]) wake();
  }

  settled(maxMs: number): Promise<ServerAuthState> {
    if (isDecisive(this.state)) return Promise.resolve(this.state);
    const waiting = new Promise<ServerAuthState>((resolve) => {
      const done = () => {
        clearTimeout(timer);
        this.waiters.delete(done);
        resolve(this.state);
      };
      const timer = setTimeout(done, maxMs);
      this.waiters.add(done);
    });
    this.requestReport();
    return waiting;
  }

  setReader(reader: () => Promise<unknown>): void {
    this.reader = reader;
  }

  requestReport(): void {
    if (!this.reader || this.reading || isDecisive(this.state)) return;
    const wait = this.lastReadAt + MIN_READ_INTERVAL_MS - Date.now();
    if (wait > 0) {
      /* Too soon after the last read: one trailing read at the interval,
         made only if someone is still waiting by then. */
      if (!this.later) {
        this.later = setTimeout(() => {
          this.later = null;
          if (this.waiters.size > 0) this.requestReport();
        }, wait);
      }
      return;
    }
    this.reading = true;
    this.lastReadAt = Date.now();
    const read = this.reader;
    void (async () => {
      try {
        await read();
      } catch {
        /* the read's own callers hear its failure; here it only means "not yet" */
      } finally {
        this.reading = false;
        /* Still undecided with someone waiting: another chance within their
           wait, spaced by the interval above. */
        if (this.waiters.size > 0) this.requestReport();
      }
    })();
  }
}
