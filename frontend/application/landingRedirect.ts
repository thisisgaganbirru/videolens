/* Who gets the landing page at `/`, and who is sent on to the tool at `/app`.

   Phase 5c moved the tool from `/` to `/app`. Every address the app ever
   handed out still points at `/` — bookmarks of `/?view=history`, the old
   manifest's `start_url` and `share_target` (`/?share-target=1&url=…`),
   home-screen installs made before the move, and the Capacitor WebView, which
   always loads `index.html` at the root. This is a static export, so there is
   no server to redirect them: the landing page's HTML carries this script,
   inline and blocking, ahead of its own content.

   Routing orchestration, hence `application/`: the same layer that owns the
   `?view=` address (useMainTab). It is a string because it has to run before
   React exists — a hydration-time redirect would paint the landing page first.

   The rules, in order:

   1. The landing document answered some other path. Capacitor's Android asset
      server answers any extensionless path it has no file for with
      `index.html` (its "html5 mode"), and the export has `app.html`, not
      `app/index.html`. So `/app` there arrives HERE. For the routes the
      export does have, hop to the real file (`/app.html`, `/privacy.html`…).
      `next start` never takes this branch: it serves `/app` itself and a 404
      for unknown paths.
   2. On `/` itself:
      - installed (the pre-paint shell script stamped `data-shell="app"`, or
        Capacitor says it is native) → `/app`, query and hash kept;
      - any query the tool understands (`view`, the share-target params) → the
        same query on `/app`, so old links and shares keep working;
      - otherwise a browser visitor: stay, and show the landing page.

   `data-redirecting` hides the body while the browser is navigating away, so
   the landing page is never painted on the way through. */

/** Query params that mean "this was meant for the tool, not the landing page". */
export const TOOL_QUERY_PARAMS = ["view", "share-target", "url", "text", "title"] as const;

/** Routes the static export writes as `<route>.html`. */
const EXPORTED_ROUTES = ["/app", "/privacy", "/terms", "/offline"] as const;

export const LANDING_REDIRECT_SCRIPT = `(function(){try{var l=window.location,r=document.documentElement,p=l.pathname.replace(/\\/+$/,"")||"/",t=l.search+l.hash;
if(p!=="/"&&p!=="/index.html"){if(${JSON.stringify(EXPORTED_ROUTES)}.indexOf(p)!==-1){r.setAttribute("data-redirecting","");l.replace(p+".html"+t);}return;}
var c=window.Capacitor,n=false;try{n=!!(c&&c.isNativePlatform&&c.isNativePlatform());}catch(e){}
var q=new URLSearchParams(l.search),d=${JSON.stringify(TOOL_QUERY_PARAMS)}.some(function(k){return q.has(k);});
function go(){r.setAttribute("data-redirecting","");l.replace("/app"+t);}
if(n||d||r.getAttribute("data-shell")==="app"){go();return;}
document.addEventListener("DOMContentLoaded",function(){if(r.getAttribute("data-shell")==="app")go();});
}catch(e){}})();`;
