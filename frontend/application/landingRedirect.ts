/* Who gets the landing page at `/`, and who is sent on to the tool at `/app`.

   Phase 5c moved the tool from `/` to `/app`. Every address the app ever
   handed out still points at `/` — bookmarks of `/?view=history`, the old
   manifest's `start_url` and `share_target` (`/?share-target=1&url=…`),
   home-screen installs made before the move, and the Capacitor WebView, which
   always loads `index.html` at the root. This is a static export, so there is
   no server to redirect them: this script runs in the root layout's `<head>`
   (app/layout.tsx), blocking, before the body is parsed.

   Routing orchestration, hence `application/`: the same layer that owns the
   `?view=` address (useMainTab). It is a string because it has to run before
   React exists — a hydration-time redirect would paint the landing page first.

   Why the root layout's <head> and not the landing page's own markup
   (refinement 1, item 9): a `<script>` rendered by a page component is part
   of that page's React tree, so a client-side navigation to it makes React
   create the element on the client — which never executes it and logs
   "Encountered a script tag while rendering React component". `next/script`
   `beforeInteractive` is no substitute: in the App Router it is queued into
   `self.__next_s` and run by Next's runtime, i.e. after first paint. The root
   layout's head is only ever hydrated, never re-created, so the script lives
   there and gates itself on the path instead of on which page rendered it.

   The rules, in order (the shell script before this one has already stamped
   `data-shell`):

   1. Capacitor's bundled export, at an extensionless route. Its Android asset
      server answers any path it has no file for with `index.html` (its "html5
      mode"), and the export has `app.html`, not `app/index.html`. So `/app`
      there would show the landing page. For the routes the export does have,
      hop to the real file (`/app.html`, `/privacy.html`…). Recognised by
      Capacitor saying it is native AND the page being served from the asset
      server's own origin (`localhost` with no port). The port check is what
      keeps live reload (`server.url` = `http://localhost:3005`, a `next dev`
      that serves `/app` itself) out of this branch, and `next start` never
      reports native at all.
      Refinement 8 (NF-01): on that same origin, an extensionless path that is
      none of those routes (`/nope`, `/app/zzz`) is answered with index.html
      too, so the landing page used to appear inside the installed app, dock
      and all, at the bad address. The landing must never show there, so it
      goes to `/404.html`, the export's not-found page (shared chrome, "Back
      to the app"). The test is the asset server's own rule: it substitutes
      index.html only when the last path segment has no `.`, so a document
      running at `/x.html` (including `/404.html` itself) is the real file and
      is left alone; that is also what keeps this from looping. A dotted path
      with no file (`/nope.txt`) gets an empty 404 from Capacitor, and no
      document runs at all, so nothing here can catch it.
   2. On `/` itself:
      - installed (`data-shell="app"`, or Capacitor says it is native) → `/app`,
        query and hash kept;
      - any query the tool understands (`view`, the share-target params) → the
        same query on `/app`, so old links and shares keep working;
      - otherwise a browser visitor: stay, and show the landing page.
   3. Any other path: nothing to do.

   `data-redirecting` hides the body while the browser is navigating away, so
   the landing page is never painted on the way through (the rule is in
   globals.css, so it applies whichever document is answering). */

/** Query params that mean "this was meant for the tool, not the landing page". */
export const TOOL_QUERY_PARAMS = ["view", "share-target", "url", "text", "title"] as const;

/* The script below is a template literal, so every regex backslash is doubled:
   `/\\/+$/` reaches the page as `/\/+$/`. A single `\/` collapses to `//`, which
   turns the rest of the line into a comment and makes the whole <head> script a
   syntax error (theme, shell, redirect and splash all stop) — refinement 1 did
   exactly that once, mid-pass. */

/** Routes the static export writes as `<route>.html`. */
const EXPORTED_ROUTES = ["/app", "/privacy", "/terms", "/offline"] as const;

/** The export's not-found page (`out/404.html`, from app/not-found.tsx). */
const NOT_FOUND_DOCUMENT = "/404.html";

export const LANDING_REDIRECT_SCRIPT = `(function(){try{var l=window.location,r=document.documentElement,p=l.pathname.replace(/\\/+$/,"")||"/",t=l.search+l.hash;
var c=window.Capacitor,n=false;try{n=!!(c&&c.isNativePlatform&&c.isNativePlatform());}catch(e){}
function go(u){r.setAttribute("data-redirecting","");l.replace(u);}
if(p!=="/"&&p!=="/index.html"){if(n&&l.hostname==="localhost"&&!l.port&&p.slice(p.lastIndexOf("/")+1).indexOf(".")===-1){go(${JSON.stringify(EXPORTED_ROUTES)}.indexOf(p)!==-1?p+".html"+t:"${NOT_FOUND_DOCUMENT}");}return;}
var q=new URLSearchParams(l.search),d=${JSON.stringify(TOOL_QUERY_PARAMS)}.some(function(k){return q.has(k);});
if(n||d||r.getAttribute("data-shell")==="app"){go("/app"+t);return;}
document.addEventListener("DOMContentLoaded",function(){if(r.getAttribute("data-shell")==="app")go("/app"+t);});
}catch(e){}})();`;
