package ai.videolens.app;

import android.content.Intent;
import android.content.res.Configuration;
import android.os.Bundle;
import android.webkit.WebView;
import androidx.core.content.ContextCompat;
import org.json.JSONObject;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        applyNightBackground();
        handleSharedText(getIntent());
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        // uiMode is in the manifest's configChanges, so a night-mode flip does
        // not recreate the activity; resources resolve against the new
        // configuration here, so re-read the colour.
        applyNightBackground();
    }

    // Refinement 3, #3. capacitor.config.ts `backgroundColor` takes one value,
    // and Bridge applies it to the WebView during super.onCreate(): light, so a
    // dark-mode launch flashed light between the splash and the page's first
    // paint. Override it with @color/app_background, which is night-qualified
    // (values/ #F6F4EE, values-night/ #0E100F, same as the splash). Same frame
    // as the Bridge's own call, before anything is drawn. It only shows until
    // the page paints its own background, so following the OS (not the app's
    // stored theme, which native cannot read yet) is right.
    private void applyNightBackground() {
        int color = ContextCompat.getColor(this, R.color.app_background);
        getWindow().getDecorView().setBackgroundColor(color);
        if (getBridge() != null) {
            WebView webView = getBridge().getWebView();
            if (webView != null) webView.setBackgroundColor(color);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleSharedText(intent);
    }

    private void handleSharedText(Intent intent) {
        if (!Intent.ACTION_SEND.equals(intent.getAction()) || !"text/plain".equals(intent.getType())) {
            return;
        }
        String sharedText = intent.getStringExtra(Intent.EXTRA_TEXT);
        if (sharedText == null || sharedText.isBlank()) {
            return;
        }

        // Consume it. Android re-delivers the launch intent to a re-created
        // activity (process death, an uncovered config change), and the web side
        // now treats an arriving share as a request to clear the screen - so a
        // replayed one would wipe a result the user is reading.
        intent.removeExtra(Intent.EXTRA_TEXT);

        String script = "localStorage.setItem('videolens-shared-text', "
            + JSONObject.quote(sharedText)
            + "); window.dispatchEvent(new Event('videolens-share'));";
        getBridge().getWebView().postDelayed(
            () -> getBridge().getWebView().evaluateJavascript(script, null),
            500
        );
    }
}
