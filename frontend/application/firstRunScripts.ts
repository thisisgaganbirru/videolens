import { SPLASH_SESSION_KEY } from "@/infrastructure/firstRunStore";

/* Phase 5d. Not a "use client" module on purpose: app/app/page.tsx (a server
   component) inlines this string into the prerendered HTML, and importing it
   from a client module would hand the server a client reference instead.

   Stamps `<html data-splash>` while the HTML is still parsing, before the
   splash element below it can paint, when all of these hold:
   - this is the installed app (the shell script in app/layout.tsx stamped
     `data-shell="app"`, or Capacitor says it is native — checked directly in
     case the bridge arrived after the shell script ran);
   - the splash has not played this session (sessionStorage);
   - sessionStorage can be read at all. If it cannot, there is no way to know
     this is a cold start, and a splash on every reload is worse than none.
   A browser tab never gets it. Removal is useSplashHandOff's job, with a CSS
   timeout behind it (app/first-run.css) so a failed hydration can never leave
   the splash covering the app. */
export const SPLASH_INIT_SCRIPT = `(function(){try{var r=document.documentElement,c=window.Capacitor,n=false;try{n=!!(c&&c.isNativePlatform&&c.isNativePlatform());}catch(e){}
if(r.getAttribute("data-shell")!=="app"&&!n)return;
try{if(window.sessionStorage.getItem(${JSON.stringify(SPLASH_SESSION_KEY)})==="1")return;}catch(e){return;}
r.setAttribute("data-splash","");}catch(e){}})();`;
