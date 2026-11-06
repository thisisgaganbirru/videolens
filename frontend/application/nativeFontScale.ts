/* Refinement 14: Android's system font scale as the root font-size.

   The installed Android app no longer lets the WebView's text zoom carry the
   system font size (text zoom multiplied px after `min(rem, px)` had compared
   the unzoomed values, so the chrome caps never held and the More sheet's em
   container queries never fired). Instead `FontScalePlugin` (frontend/android)
   pins text zoom to 100 and injects a document-start script that sets
   `window.__videolensFontScale` and, if the root element already exists, its
   inline font-size. A document-start script can run before `<html>` exists,
   so this blocking head script applies the same value before the body parses,
   i.e. before the first paint.

   On the web the global is never set and this is a no-op: the user's own
   browser text-size setting stays the root font size, untouched. A live change
   on Android is applied by the native side directly (evaluateJavascript), not
   here. Keep the global's name in sync with FontScaleScript.GLOBAL. */
export const NATIVE_FONT_SCALE_GLOBAL = "__videolensFontScale";

export const FONT_SCALE_INIT_SCRIPT = `(function(){try{var s=window[${JSON.stringify(
  NATIVE_FONT_SCALE_GLOBAL
)}];if(typeof s==="number"&&s>0&&s!==1)document.documentElement.style.fontSize=Math.round(s*10000)/100+"%";}catch(e){}})();`;
