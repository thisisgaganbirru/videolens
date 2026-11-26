import { Capacitor, type PluginListenerHandle } from "@capacitor/core";
import type { AuthRedirectBrowser } from "@/domain/ports";

/* Where Google's consent page is shown and how its answer comes back (auth
   phase 4, docs/frontend/auth-sign-in.md, "Google"). Behind the
   `AuthRedirectBrowser` port; `authSession.ts` drives it and is the only
   caller.

   Web: the tab itself goes to the consent page, and Supabase sends it back to
   `/app?view=account&code=...` (or `&error=...`). PKCE: the verifier waits in
   this origin's localStorage, so the return must land on the same origin.

   Installed app: Google refuses sign-in inside embedded WebViews, so the page
   opens in the system browser (`@capacitor/browser`, a Custom Tab on
   Android) and Supabase sends it to `<applicationId>://auth/callback`, which
   the manifest's intent filter hands to the running activity (`appUrlOpen`
   from `@capacitor/app`), or which launched the app (`getLaunchUrl`) if the
   system had closed it meanwhile. Both plugins are loaded only there, with a
   dynamic `import()`, so the web bundle carries neither for this.

   The scheme is the build's own application id (`App.getInfo().id`), because
   the manifest registers `${applicationId}`: production is
   `ai.videolens.app`, the dev lane's APK (`-PdevBuild`, `.dev` suffix) is
   `ai.videolens.app.dev`. With both installed each catches only its own
   return, so the PKCE verifier is always in the app that receives the code. */

/** Production's scheme, and the fallback when the id cannot be read. */
const DEFAULT_NATIVE_SCHEME = "ai.videolens.app";
const NATIVE_RETURN_HOST = "auth";
const NATIVE_RETURN_PATH = "/callback";

/** Production's return address. Each build's own (see `nativeReturnUrl`)
 *  must match its manifest filter and an entry in its Supabase project's
 *  redirect allowlist exactly. */
export const NATIVE_RETURN_URL = nativeReturnUrl(DEFAULT_NATIVE_SCHEME);

export function nativeReturnUrl(scheme: string): string {
  return `${scheme}://${NATIVE_RETURN_HOST}${NATIVE_RETURN_PATH}`;
}

/** An application id usable as a URL scheme as it stands (a package name
 *  may hold `_`, which a scheme may not). Lowercase only: Android matches
 *  intent-filter schemes case-sensitively and URL parsing lowercases them. */
const SCHEME_SHAPE = /^[a-z][a-z0-9+.-]*$/;

/** The Account view, where a web return lands. Same address the tab bar
 *  uses (`mainTabHref("account")`); spelled out because infrastructure does
 *  not import the application layer. */
const WEB_RETURN_PATH = "/app";
const WEB_RETURN_VIEW = "account";

/** The parameters a provider return carries, and the ones removed from the
 *  address bar once read. `sb_flow_id` is supabase-js's optional flow id. */
const RETURN_PARAMS = ["code", "error", "error_code", "error_description", "sb_flow_id"] as const;

function isNative(): boolean {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
}

function hashParams(url: URL): URLSearchParams {
  return new URLSearchParams(url.hash.startsWith("#") ? url.hash.slice(1) : url.hash);
}

/** A return carries a code or an error, in the query or (implicit-style
 *  errors) the fragment. */
function carriesReturn(url: URL): boolean {
  const hash = hashParams(url);
  return RETURN_PARAMS.some((name) => name !== "sb_flow_id" && (url.searchParams.has(name) || hash.has(name)));
}

/** The current page is the web return: the app document on the Account view
 *  with a code or an error on it. Any other page's `?code=` is not ours. */
function isWebReturn(url: URL): boolean {
  const path = url.pathname.replace(/\/+$/, "");
  return (
    (path === WEB_RETURN_PATH || path === `${WEB_RETURN_PATH}.html`) &&
    url.searchParams.get("view") === WEB_RETURN_VIEW &&
    carriesReturn(url)
  );
}

/** The app's deep link under `scheme`, and only that exact address. */
export function isNativeReturn(raw: string, scheme: string = DEFAULT_NATIVE_SCHEME): boolean {
  try {
    const url = new URL(raw);
    return (
      url.protocol === `${scheme}:` &&
      url.host === NATIVE_RETURN_HOST &&
      url.pathname.replace(/\/+$/, "") === NATIVE_RETURN_PATH
    );
  } catch {
    return false;
  }
}

/** Removes the return's parameters from the address bar in place, keeping
 *  the view, other params and the history entry's own state. A fresh state
 *  object without Next's internal keys: Next's patched replaceState skips its
 *  `useSearchParams` sync when handed its own state (see `takeSearchParam` in
 *  application/useMainTab.ts, which does the same for the billing return). */
function stripWebReturn(url: URL): void {
  const clean = new URL(url.href);
  for (const name of RETURN_PARAMS) clean.searchParams.delete(name);
  const hash = hashParams(clean);
  if (RETURN_PARAMS.some((name) => hash.has(name))) clean.hash = "";
  const current: unknown = window.history.state;
  const state: Record<string, unknown> = {};
  if (current && typeof current === "object") {
    for (const [key, value] of Object.entries(current as Record<string, unknown>)) {
      if (key !== "__NA" && key !== "__PRIVATE_NEXTJS_INTERNALS_TREE") state[key] = value;
    }
  }
  window.history.replaceState(state, "", `${clean.pathname}${clean.search}${clean.hash}`);
}

type BrowserModule = typeof import("@capacitor/browser");
type AppModule = typeof import("@capacitor/app");

export class SystemAuthBrowser implements AuthRedirectBrowser {
  private plugins: Promise<[BrowserModule, AppModule]> | null = null;
  private scheme: Promise<string> | null = null;

  /** This build's deep-link scheme: its application id, read once. Never
   *  rejects; production's scheme when the bridge or the id is unusable. */
  private nativeScheme(): Promise<string> {
    if (!this.scheme) {
      this.scheme = this.native()
        .then(([, { App }]) => App.getInfo())
        .then(({ id }) => (typeof id === "string" && SCHEME_SHAPE.test(id) ? id : DEFAULT_NATIVE_SCHEME))
        .catch(() => DEFAULT_NATIVE_SCHEME);
    }
    return this.scheme;
  }

  /** The two Capacitor plugins, loaded once and only in the app. */
  private native(): Promise<[BrowserModule, AppModule]> {
    if (!this.plugins) {
      this.plugins = Promise.all([import("@capacitor/browser"), import("@capacitor/app")]).catch((err) => {
        this.plugins = null;
        throw err;
      });
    }
    return this.plugins;
  }

  async returnUrl(): Promise<string> {
    if (isNative()) return nativeReturnUrl(await this.nativeScheme());
    return `${window.location.origin}${WEB_RETURN_PATH}?view=${WEB_RETURN_VIEW}`;
  }

  async open(url: string): Promise<void> {
    if (!isNative()) {
      window.location.assign(url);
      return;
    }
    const [{ Browser }] = await this.native();
    await Browser.open({ url });
  }

  async close(): Promise<void> {
    if (!isNative()) return;
    try {
      const [{ Browser }] = await this.native();
      await Browser.close();
    } catch {
      /* already closed, or no browser to close */
    }
  }

  async takeInitialReturn(): Promise<string | null> {
    if (!isNative()) {
      if (typeof window === "undefined") return null;
      const here = new URL(window.location.href);
      if (!isWebReturn(here)) return null;
      stripWebReturn(here);
      return here.href;
    }
    try {
      const [, { App }] = await this.native();
      const [launch, scheme] = await Promise.all([App.getLaunchUrl(), this.nativeScheme()]);
      return launch?.url && isNativeReturn(launch.url, scheme) ? launch.url : null;
    } catch {
      return null;
    }
  }

  watch(handlers: { onReturn(url: string): void; onClosed(): void }): () => void {
    if (typeof window === "undefined") return () => {};
    if (!isNative()) {
      /* Back from Google's page restores this tab from the back/forward
         cache with its state as it was: still "opening Google". */
      const onPageShow = (event: PageTransitionEvent) => {
        if (event.persisted) handlers.onClosed();
      };
      window.addEventListener("pageshow", onPageShow);
      return () => window.removeEventListener("pageshow", onPageShow);
    }
    const handles: PluginListenerHandle[] = [];
    let removed = false;
    const keep = (handle: PluginListenerHandle) => {
      if (removed) void handle.remove();
      else handles.push(handle);
    };
    this.native()
      .then(async ([{ Browser }, { App }]) => {
        const scheme = await this.nativeScheme();
        keep(
          await App.addListener("appUrlOpen", ({ url }) => {
            if (isNativeReturn(url, scheme)) handlers.onReturn(url);
          })
        );
        keep(await Browser.addListener("browserFinished", () => handlers.onClosed()));
      })
      .catch(() => {
        /* no bridge: nothing can come back, and nothing was opened */
      });
    return () => {
      removed = true;
      for (const handle of handles) void handle.remove();
    };
  }
}

/** The return's parameters, from the query and the fragment. */
export function readReturn(raw: string): { code: string | null; error: string | null; errorCode: string | null; description: string | null } {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { code: null, error: "invalid_request", errorCode: null, description: null };
  }
  const hash = hashParams(url);
  const pick = (name: string) => url.searchParams.get(name) ?? hash.get(name);
  return { code: pick("code"), error: pick("error"), errorCode: pick("error_code"), description: pick("error_description") };
}
