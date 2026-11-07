package ai.videolens.app;

import android.content.res.Configuration;
import android.net.Uri;
import android.webkit.WebView;
import androidx.webkit.ScriptHandler;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.getcapacitor.Logger;
import com.getcapacitor.Plugin;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.Collections;

/**
 * Refinement 14: Android's system font scale reaches the page as the root
 * font-size, the same model a browser's text-size setting uses on the web.
 *
 * Before this (refinement 11) it reached the page as WebView text zoom: the
 * WebView seeds its textZoom from the font scale when its settings are created
 * (Capacitor never touches it), and MainActivity re-applied it on a live
 * change. Text zoom multiplies font sizes after layout has resolved them, so
 * `min(1.1875rem, 22px)` compared the unzoomed 19 against 22 and then came out
 * as 38px at font 2.0, and the More sheet's em container queries never fired
 * (android-66, run 15). With text zoom pinned to 100 and the scale on the root
 * instead, rem, em container queries and the px caps all see one text size,
 * as they do in a desktop browser and in the Playwright harness.
 *
 * How the scale gets in, and why this way:
 * - A document-start script (androidx.webkit addDocumentStartJavaScript, the
 *   mechanism Capacitor itself uses for its bridge) runs in every document of
 *   the app's origin before any page script, so the value is there before the
 *   first paint on a cold launch, after a reload and on a document navigation
 *   (/privacy, /offline), with nothing stored and nothing to go stale. It sets
 *   window.__videolensFontScale and, when the root element already exists, its
 *   font-size; the page's own blocking head script (application/
 *   nativeFontScale.ts) applies it otherwise, still before the body parses.
 * - A live change (fontScale is in configChanges, so the activity survives)
 *   arrives in handleOnConfigurationChanged: the document-start script is
 *   swapped for one with the new value, and the same script is evaluated in
 *   the current document so the change shows immediately, state intact.
 * - It is a plugin only for Capacitor's lifecycle: load() runs inside the
 *   Bridge constructor after the WebView settings are made and before the app
 *   URL is loaded, the one point where a document-start script is guaranteed
 *   to cover the first document. It exposes no methods to the page.
 *
 * Fallback: a WebView without DOCUMENT_START_SCRIPT (older than ~M87; minSdk 24
 * devices with an unupdated WebView) keeps the refinement 11 behaviour, text
 * zoom = font scale, so its text still follows the system setting.
 */
@CapacitorPlugin(name = "FontScale")
public class FontScalePlugin extends Plugin {

    private ScriptHandler startScript;
    private boolean rootFontSize;
    private float applied = -1f;

    @Override
    public void load() {
        rootFontSize = WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT);
        apply(getContext().getResources().getConfiguration().fontScale, false);
    }

    @Override
    protected void handleOnConfigurationChanged(Configuration newConfig) {
        apply(newConfig.fontScale, true);
    }

    private void apply(float fontScale, boolean live) {
        float scale = FontScaleScript.sanitise(fontScale);
        if (scale == applied) return;
        applied = scale;
        WebView webView = getBridge() == null ? null : getBridge().getWebView();
        if (webView == null) return;

        if (rootFontSize) {
            String js = FontScaleScript.script(scale);
            try {
                ScriptHandler next = WebViewCompat.addDocumentStartJavaScript(webView, js, Collections.singleton(appOrigin()));
                if (startScript != null) startScript.remove();
                startScript = next;
                // Pin it: the WebView seeded textZoom from the font scale when
                // its settings were created; the root font-size replaces that.
                webView.getSettings().setTextZoom(100);
                if (live) webView.evaluateJavascript(js, null);
                return;
            } catch (IllegalArgumentException | UnsupportedOperationException ex) {
                Logger.warn("FontScale", "document-start script refused, using text zoom: " + ex.getMessage());
                rootFontSize = false;
            }
        }
        webView.getSettings().setTextZoom(FontScaleScript.textZoomPercent(scale));
    }

    /** The app's origin (https://localhost), built the way Capacitor's Bridge builds it. */
    private String appOrigin() {
        return Uri.parse(getBridge().getAppUrl()).buildUpon().path(null).fragment(null).clearQuery().build().toString();
    }
}
