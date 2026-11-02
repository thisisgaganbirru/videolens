package ai.videolens.app;

import android.app.UiModeManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.content.res.Resources;
import android.os.Build;
import android.os.PowerManager;
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
 *
 * Refinement 7, THM-01b-6: it also reports the OS's own night state
 * (getSystemNight(), and a "systemNightChanged" { dark } event), because the
 * WebView's prefers-color-scheme cannot be trusted for it once the app has
 * forced a mode. Reproduced on API 35 / WebView 124: cold launch with Light
 * stored (activity starts forced NIGHT_NO), switch to System, then flip the
 * OS to light: the bars follow, but matchMedia('(prefers-color-scheme: dark)')
 * stays true until a cold relaunch. Chromium derives that media feature from
 * the WebView's (activity) context, whose configuration and theme were built
 * under the forced override; once the override is lifted it no longer tracks
 * the real system uiMode reliably. With System chosen, the web side now paints
 * from this value and keeps matchMedia only as the browser fallback.
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

    /** Last value sent with "systemNightChanged", so repeats are not re-sent. */
    private Boolean lastSystemNight = null;

    /**
     * Whether the OS (not this app) is in night mode right now.
     *
     * UiModeManager.getNightMode() first: it is the user-wide setting
     * (Settings > Dark theme, `cmd uimode night`), held by the system service,
     * and never reflects this app's own override: AppCompat's default night
     * mode only overrides the activity's configuration, and
     * setApplicationNightMode (API 31+) is stored per package, separately
     * from the global mode getNightMode() returns. YES and NO are therefore
     * the answer as long as Battery Saver is off: on Android 10+ Battery Saver
     * also forces the dark theme without touching that setting.
     *
     * AUTO / CUSTOM (a schedule, sunset to sunrise) and Battery Saver only say
     * what decides, not what was decided. There the night bit of
     * Resources.getSystem()'s configuration is the current state. That object
     * is the process configuration, which on API 31+ includes the per-package
     * override from setApplicationNightMode, but the web side only asks while
     * System is chosen, and choosing System clears that override
     * (MODE_NIGHT_AUTO maps to "undefined" in UiModeManagerService), so there
     * it is the OS's own value. It is never the activity's configuration,
     * which is the one AppCompat overrides.
     */
    static boolean systemNight(Context context) {
        try {
            UiModeManager manager = (UiModeManager) context.getSystemService(Context.UI_MODE_SERVICE);
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            boolean saver = power != null && power.isPowerSaveMode();
            if (manager != null && !saver) {
                int mode = manager.getNightMode();
                if (mode == UiModeManager.MODE_NIGHT_YES) return true;
                if (mode == UiModeManager.MODE_NIGHT_NO) return false;
            }
        } catch (RuntimeException ignored) {
            // Fall through to the configuration.
        }
        int night = Resources.getSystem().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return night == Configuration.UI_MODE_NIGHT_YES;
    }

    /** getSystemNight() resolves { dark }: the OS night state, see systemNight(). */
    @PluginMethod
    public void getSystemNight(final PluginCall call) {
        boolean dark = systemNight(getContext().getApplicationContext());
        lastSystemNight = dark;
        JSObject result = new JSObject();
        result.put("dark", dark);
        call.resolve(result);
    }

    /**
     * Fires "systemNightChanged" { dark } when the OS night state differs from
     * the last value reported. Called on every configuration change (uiMode is
     * in configChanges, so an OS flip lands here rather than recreating) and on
     * resume (a flip while backgrounded, or one whose configuration change the
     * forced app mode swallowed).
     */
    void reportSystemNight() {
        boolean dark = systemNight(getContext().getApplicationContext());
        if (lastSystemNight != null && lastSystemNight == dark) return;
        lastSystemNight = dark;
        JSObject data = new JSObject();
        data.put("dark", dark);
        notifyListeners("systemNightChanged", data);
    }

    @Override
    protected void handleOnConfigurationChanged(Configuration newConfig) {
        super.handleOnConfigurationChanged(newConfig);
        reportSystemNight();
    }

    @Override
    protected void handleOnResume() {
        super.handleOnResume();
        reportSystemNight();
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
                // Lifting or setting the per-package override can move the
                // configuration fallback in systemNight(); re-check now.
                reportSystemNight();
            }
            JSObject result = new JSObject();
            result.put("changed", changed);
            call.resolve(result);
        });
    }
}
