import type { Clerk } from "@clerk/clerk-js";
import type { AuthUser } from "@/domain/entities";
import type { AuthSession } from "@/domain/ports";

/* The identity provider, behind the `AuthSession` port.

   Config-gated on `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`. With no key the
   container builds `NullAuthSession`, which is what "accounts are not set up
   on this deployment" looks like to the rest of the app: no token on any
   request, no user, and a sign-in button that is not rendered. The Clerk SDK
   is loaded with a dynamic `import()` so a deployment that never configures it
   never ships it — it is a few hundred kilobytes, and the PWA's precache is
   measured.

   Nothing outside this file names Clerk. The hooks see `AuthUser` and a
   token; the API sees a bearer JWT it verifies against the provider's JWKS
   (`AUTH_JWKS_URL` on the backend). Swapping providers is this file plus
   three backend env vars. */

export class NullAuthSession implements AuthSession {
  readonly enabled = false;

  async load(): Promise<void> {}

  user(): AuthUser | null {
    return null;
  }

  async getToken(): Promise<string | null> {
    return null;
  }

  async signIn(): Promise<void> {}

  async signOut(): Promise<void> {}

  subscribe(): () => void {
    return () => {};
  }
}

export class ClerkAuthSession implements AuthSession {
  readonly enabled = true;

  private clerk: Clerk | null = null;
  private loading: Promise<void> | null = null;
  private readonly listeners = new Set<() => void>();

  constructor(private readonly publishableKey: string) {}

  load(): Promise<void> {
    if (!this.loading) {
      this.loading = import("@clerk/clerk-js")
        .then(async ({ Clerk }) => {
          const clerk = new Clerk(this.publishableKey);
          await clerk.load();
          this.clerk = clerk;
          clerk.addListener(() => this.notify());
          this.notify();
        })
        .catch((err) => {
          /* A provider that will not load must not take the app down with it:
             the session stays "signed out" and every request goes out
             anonymous. Reset so a later call can try again. */
          this.loading = null;
          throw err;
        });
    }
    return this.loading;
  }

  user(): AuthUser | null {
    const user = this.clerk?.user;
    if (!user) return null;
    return {
      id: user.id,
      email: user.primaryEmailAddress?.emailAddress ?? null,
      name: user.fullName ?? null,
      imageUrl: user.imageUrl ?? null,
    };
  }

  async getToken(): Promise<string | null> {
    /* Waits for the SDK so the first requests of a page load (history on
       mount, the account panel) are not sent anonymous a beat before the
       session is known. A provider that fails to load resolves `null`. */
    try {
      await this.load();
    } catch {
      return null;
    }
    return (await this.clerk?.session?.getToken()) ?? null;
  }

  async signIn(): Promise<void> {
    await this.load();
    this.clerk?.openSignIn();
  }

  async signOut(): Promise<void> {
    await this.clerk?.signOut();
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

export function buildAuthSession(): AuthSession {
  const key = (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY || "").trim();
  return key ? new ClerkAuthSession(key) : new NullAuthSession();
}
