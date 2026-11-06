package ai.videolens.app;

/**
 * Refinement 14: the JavaScript FontScalePlugin hands the page. Pure Java, no
 * Android types, so it is unit-tested on the host (FontScaleScriptTest).
 *
 * The page side is `application/nativeFontScale.ts`: its pre-paint head script
 * reads the same global and applies the same root font-size, for the case
 * where `document.documentElement` does not exist yet when a document-start
 * script runs.
 */
final class FontScaleScript {

    /** Window global the page reads; keep in sync with NATIVE_FONT_SCALE_GLOBAL. */
    static final String GLOBAL = "__videolensFontScale";

    private FontScaleScript() {}

    /**
     * Android's font scale as a usable number: 1 for a missing or nonsense
     * value, otherwise clamped to 0.5-3 (the system offers 0.85-2.0).
     */
    static float sanitise(float fontScale) {
        if (Float.isNaN(fontScale) || Float.isInfinite(fontScale) || fontScale <= 0f) return 1f;
        return Math.max(0.5f, Math.min(3f, fontScale));
    }

    /** The old (refinement 11) text zoom, kept for WebViews without document-start scripts. */
    static int textZoomPercent(float fontScale) {
        return Math.round(sanitise(fontScale) * 100f);
    }

    /**
     * Records the scale on window and, when the root element exists, sets it as
     * the root font-size (a percentage of the WebView's 16px default, so rem,
     * em container queries and every min(rem, px) cap all see one text size).
     * Scale 1 clears the inline value, leaving the stylesheet's own root size.
     */
    static String script(float fontScale) {
        String s = String.valueOf(sanitise(fontScale));
        return "(function(){var s=" + s + ";window." + GLOBAL + "=s;"
            + "var r=document.documentElement;"
            + "if(r)r.style.fontSize=s===1?\"\":Math.round(s*10000)/100+\"%\";})();";
    }
}
