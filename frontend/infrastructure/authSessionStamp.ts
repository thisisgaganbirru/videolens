/* Pre-paint session stamp (2026-11-14). The one other file that knows where
   the identity provider keeps its session: `authSession.ts` uses
   `providerStorageKey` for the same key, so the two cannot drift.

   The prerendered /app cannot know whether someone is signed in, and the
   provider only loads after hydration. `data-session` on <html> lets CSS act
   on "a session is stored here" before then (today: the Gemini key page's
   held sign-in line, which a signed-in visit never shows). Only presence is
   read; the token never leaves storage. A stored session may turn out to be
   expired, so this is a layout hint, never a statement of who is signed in. */

export const SESSION_ATTRIBUTE = "data-session";

/** supabase-js's own default storage key for a project URL. */
export function providerStorageKey(url: string): string {
  let ref = "default";
  try {
    ref = new URL(url).hostname.split(".")[0] || ref;
  } catch {
    /* an invalid URL fails at load, where it is reported */
  }
  return `sb-${ref}-auth-token`;
}

/* Read as two literal `process.env.NEXT_PUBLIC_*` expressions so Next inlines
   them; with sign-in unconfigured the script is empty and stamps nothing. */
const url = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
const key = (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "").trim();

export const SESSION_INIT_SCRIPT =
  url && key
    ? `(function(){try{if(localStorage.getItem(${JSON.stringify(
        providerStorageKey(url)
      )}))document.documentElement.setAttribute(${JSON.stringify(SESSION_ATTRIBUTE)},"");}catch(e){}})();`
    : "";
