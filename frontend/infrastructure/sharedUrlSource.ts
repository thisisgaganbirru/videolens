import type { SharedUrlSource } from "@/domain/ports";

/* Where the native side leaves a share. `MainActivity.handleSharedText` writes
   the shared text here and then dispatches the event below, because a WebView
   has no other way to hand a string to the page it is showing. */
const NATIVE_TEXT_KEY = "videolens-shared-text";
const NATIVE_EVENT = "videolens-share";

/* The params the web manifest's `share_target` sends (`app/manifest.ts`), plus
   the marker on its action URL. All four are stripped once read. */
const SHARE_PARAMS = ["url", "text", "title", "share-target"] as const;

const URL_IN_TEXT = /https?:\/\/\S+/;

/** The first http(s) URL in a shared blob of text — apps share "caption + link",
 *  rarely a bare URL. */
function firstUrl(text: string | null | undefined): string | null {
  return text?.match(URL_IN_TEXT)?.[0] ?? null;
}

export class WebShareUrlSource implements SharedUrlSource {
  take(): string | null {
    if (typeof window === "undefined") return null;
    /* Both are drained on every call, not just until one hits: a share whose
       text carried no URL used to sit in localStorage forever and surface later
       as a phantom prefill. */
    const native = this.takeNativeText();
    const query = this.takeQueryParams();
    return native ?? query;
  }

  subscribe(listener: () => void): () => void {
    if (typeof window === "undefined") return () => {};
    window.addEventListener(NATIVE_EVENT, listener);
    return () => window.removeEventListener(NATIVE_EVENT, listener);
  }

  private takeNativeText(): string | null {
    try {
      const raw = window.localStorage.getItem(NATIVE_TEXT_KEY);
      if (raw === null) return null;
      window.localStorage.removeItem(NATIVE_TEXT_KEY);
      return firstUrl(raw);
    } catch {
      /* Storage can throw outright (private mode, blocked site data). A share
         we cannot read is not worth taking the app down for. */
      return null;
    }
  }

  private takeQueryParams(): string | null {
    const params = new URLSearchParams(window.location.search);
    if (!SHARE_PARAMS.some((param) => params.has(param))) return null;

    const shared = firstUrl(params.get("url")) ?? firstUrl(params.get("text"));
    for (const param of SHARE_PARAMS) params.delete(param);

    /* Strip the share out of the address before returning it. The params are
       part of the URL the PWA was launched at, so leaving them would re-deliver
       the same link on every remount — and `?view=` tab switches are pushState,
       so pressing back would walk right back into it. `replaceState` keeps the
       rest of the query (the tab) and adds no history entry. */
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      query ? `${window.location.pathname}?${query}` : window.location.pathname
    );
    return shared;
  }
}
