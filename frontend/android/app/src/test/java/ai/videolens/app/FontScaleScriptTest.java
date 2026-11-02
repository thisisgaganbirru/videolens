package ai.videolens.app;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class FontScaleScriptTest {

    @Test
    public void sanitiseKeepsSystemScales() {
        assertEquals(1f, FontScaleScript.sanitise(1f), 0f);
        assertEquals(1.3f, FontScaleScript.sanitise(1.3f), 0f);
        assertEquals(2f, FontScaleScript.sanitise(2f), 0f);
    }

    @Test
    public void sanitiseRejectsNonsense() {
        assertEquals(1f, FontScaleScript.sanitise(Float.NaN), 0f);
        assertEquals(1f, FontScaleScript.sanitise(0f), 0f);
        assertEquals(1f, FontScaleScript.sanitise(-2f), 0f);
        assertEquals(1f, FontScaleScript.sanitise(Float.POSITIVE_INFINITY), 0f);
        assertEquals(3f, FontScaleScript.sanitise(9f), 0f);
        assertEquals(0.5f, FontScaleScript.sanitise(0.1f), 0f);
    }

    @Test
    public void textZoomFallbackMatchesRefinement11() {
        assertEquals(100, FontScaleScript.textZoomPercent(1f));
        assertEquals(115, FontScaleScript.textZoomPercent(1.15f));
        assertEquals(200, FontScaleScript.textZoomPercent(2f));
    }

    @Test
    public void scriptSetsGlobalAndRootFontSize() {
        String js = FontScaleScript.script(1.3f);
        assertTrue(js, js.contains("var s=1.3;"));
        assertTrue(js, js.contains("window.__videolensFontScale=s;"));
        assertTrue(js, js.contains("r.style.fontSize=s===1?\"\":Math.round(s*10000)/100+\"%\""));
    }

    @Test
    public void scriptUsesADotDecimalWhateverTheLocale() {
        java.util.Locale before = java.util.Locale.getDefault();
        try {
            java.util.Locale.setDefault(java.util.Locale.GERMANY);
            assertTrue(FontScaleScript.script(1.15f).contains("var s=1.15;"));
        } finally {
            java.util.Locale.setDefault(before);
        }
    }

    @Test
    public void scriptForScaleOneIsAPlainNumber() {
        assertTrue(FontScaleScript.script(1f).contains("var s=1.0;"));
    }
}
