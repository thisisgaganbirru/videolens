package ai.videolens.app;

import android.content.Intent;
import android.os.Bundle;
import org.json.JSONObject;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handleSharedText(getIntent());
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

        String script = "localStorage.setItem('videolens-shared-text', "
            + JSONObject.quote(sharedText)
            + "); window.dispatchEvent(new Event('videolens-share'));";
        getBridge().getWebView().postDelayed(
            () -> getBridge().getWebView().evaluateJavascript(script, null),
            500
        );
    }
}
