package ai.videolens.app;

import android.app.UiModeManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import androidx.appcompat.app.AppCompatDelegate;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Refinement 5, THM-01b: the app's own theme choice (System / Light / Dark in
 * the More sheet), mirrored into native storage so the next launch can apply
 * it before the first frame.
 *
 * Before this, everything native (launch screen, window background, the
 * DEFAULT-styled system bars) followed the OS night mode, because the choice
 * lived only in the WebView's localStorage. With Light chosen and the OS dark,
 * a relaunch showed a dark window and dark bars, then the light page.
 *
 * - The web side calls setPreference({ value }) whenever the choice changes
 *   (and once per launch, so a choice made before this release is picked up).
 * - MainActivity.attachBaseContext reads it back and sets AppCompat's default
 *   night mode before AppCompat resolves the activity's configuration, so the
 *   night-qualified resources (@color/app_background, the splash colours) and
 *   SystemBars' DEFAULT style resolve against the app's choice.
 * - On Android 12+ it also tells UiModeManager, which the system persists for
 *   the package and uses for the launch screen it draws before any app code
 *   runs. Below 12 the launch screen still follows the OS: there is no hook.
 *
 * A live change does not recreate the activity: uiMode is in the manifest's
 * configChanges, and AppCompat then updates the resources and calls
 * onConfigurationChanged instead of recreating (AppCompatDelegateImpl
 * .updateAppConfiguration). The WebView and its state stay as they are.
 */
@CapacitorPlugin(name = "NativeTheme")
public class NativeThemePlugin extends Plugin {

    static final String PREFS = "videolens_native_theme";
    static final String KEY = "preference";
    static final String SYSTEM = "system";
    static final String LIGHT = "light";
    static final String DARK = "dark";

    /** The stored choice, "system" when nothing (or something unknown) is stored. */
    static String storedPreference(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        return normalise(prefs.getString(KEY, SYSTEM));
    }

    static String normalise(String value) {
        if (LIGHT.equals(value) || DARK.equals(value)) return value;
        return SYSTEM;
    }

    static int appCompatMode(String preference) {
        if (LIGHT.equals(preference)) return AppCompatDelegate.MODE_NIGHT_NO;
        if (DARK.equals(preference)) return AppCompatDelegate.MODE_NIGHT_YES;
        return AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM;
    }

    /** Called from MainActivity.attachBaseContext, before AppCompat reads it. */
    static void applyStored(Context context) {
        try {
            AppCompatDelegate.setDefaultNightMode(appCompatMode(storedPreference(context)));
        } catch (RuntimeException ignored) {
            // Cosmetic only: a failure leaves the OS night mode in charge.
        }
    }

    private static void applySystemNightMode(Context context, String preference) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return;
        try {
            UiModeManager manager = (UiModeManager) context.getSystemService(Context.UI_MODE_SERVICE);
            if (manager == null) return;
            int mode = LIGHT.equals(preference)
                ? UiModeManager.MODE_NIGHT_NO
                : DARK.equals(preference) ? UiModeManager.MODE_NIGHT_YES : UiModeManager.MODE_NIGHT_AUTO;
            manager.setApplicationNightMode(mode);
        } catch (RuntimeException ignored) {
            // Launch screen keeps following the OS; everything after it still follows the app.
        }
    }

    /**
     * setPreference({ value: "system" | "light" | "dark" }) resolves
     * { changed }: whether the native mode had to change. Unchanged is a no-op
     * (the once-per-launch mirror lands here almost every time).
     */
    @PluginMethod
    public void setPreference(final PluginCall call) {
        final String preference = normalise(call.getString("value", SYSTEM));
        final Context context = getContext().getApplicationContext();
        final boolean changed = !preference.equals(storedPreference(context));
        if (changed) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, preference).apply();
        }
        getBridge().executeOnMainThread(() -> {
            if (changed) {
                try {
                    // Synchronous for this activity: its resources are on the
                    // new night mode before any later bridge call (SystemBars'
                    // DEFAULT style) is resolved on the main thread.
                    AppCompatDelegate.setDefaultNightMode(appCompatMode(preference));
                } catch (RuntimeException ignored) {
                    // Leave the current mode; the stored value still applies next launch.
                }
                applySystemNightMode(context, preference);
            }
            JSObject result = new JSObject();
            result.put("changed", changed);
            call.resolve(result);
        });
    }
}
