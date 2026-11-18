package ma.pixiedust.app.core;

import android.content.Context;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

import ma.pixiedust.app.R;

/**
 * Offline list of the router models, chipset strings and firmware placeholders
 * that PixieDust users actually meet in the field (TP-Link, Archer, D-Link,
 * Asus, Zyxel, Ralink/Realtek chipsets...).
 *
 * <p>The list ships inside the APK ({@code res/raw/known_models.txt}) so the
 * highlight works with no network at all. Matching is deliberately tolerant:
 * the WPS information element is a free-text field, so the same box may report
 * {@code TL-WR841N}, {@code TP-LINK Wireless Router TL-WR841N} or
 * {@code TL-WR841N 14.0}. Everything is compared in a compact form (letters and
 * digits only, lower case), with a trailing hardware version dropped.
 *
 * <p>A generic label is <em>not</em> a model. Strings such as {@code Wireless AP},
 * {@code Wireless Access Point} or {@code WPS Router} only describe the device
 * class; they never turn a network into a "Pixie" target on their own. At least
 * one real model token (a token containing a digit, e.g. {@code TL-WR841N},
 * {@code RT2860}, {@code DIR-615}) has to be present before the tolerant
 * substring matching is allowed to run.
 */
public final class KnownModels {

    private static final Object LOCK = new Object();
    private static volatile Set<String> keys;

    /** Compact forms of labels that describe a device class, not a model. */
    private static final Set<String> GENERIC = new HashSet<>(Arrays.asList(
            "ap", "wifiap", "wirelessap", "aprouter", "wirelessapprouter",
            "wireless", "wirelessaccess", "accesspoint", "wirelessaccesspoint",
            "router", "wirelessrouter", "wpsrouter", "routerwps",
            "wifi", "wps", "wifiprotectedsetup", "protectedsetup", "setup",
            "network", "networkdevice", "device", "default", "hostname",
            "gateway", "modem", "internet", "home", "series", "box"
    ));

    private KnownModels() {
    }

    /** True when this model string appears in the known list. */
    public static boolean matches(Context context, String model) {
        if (context == null) {
            return false;
        }
        String mine = compact(model);
        if (mine.length() < 3) {
            return false;
        }
        Set<String> all = keys(context);

        // Exact hit first: this is what keeps firmware placeholders such as
        // "<#ZVMODELVZ#>" and bare chipset strings working.
        if (all.contains(mine)) {
            return true;
        }

        // Never promote a generic class name ("Wireless AP") to a known model.
        if (!hasModelToken(model)) {
            return false;
        }

        for (String key : all) {
            // "TP-LINK Wireless Router TL-WR841N" contains "tlwr841n"
            if (key.length() >= 5 && mine.contains(key)) {
                return true;
            }
            // "<#ZVMODELVZ#>" is only ever reported with its "Wireless WPS Router" prefix
            if (mine.length() >= 5 && key.contains(mine)) {
                return true;
            }
        }
        return false;
    }

    /** A token with a digit that is not one of the generic class labels. */
    private static boolean hasModelToken(String value) {
        if (value == null) {
            return false;
        }
        String[] parts = value.split("[^A-Za-z0-9]+");
        for (String part : parts) {
            String token = compact(part);
            if (token.length() < 3 || GENERIC.contains(token) || !hasDigit(token)) {
                continue;
            }
            // A bare hardware version ("1.0", "v3") is not a model either.
            if (part.matches("(?i)v?\\d{1,2}(\\.\\d+)*")) {
                continue;
            }
            return true;
        }
        return false;
    }

    private static Set<String> keys(Context context) {
        Set<String> local = keys;
        if (local != null) {
            return local;
        }
        synchronized (LOCK) {
            if (keys == null) {
                keys = load(context.getApplicationContext());
            }
            return keys;
        }
    }

    private static Set<String> load(Context context) {
        Set<String> out = new HashSet<>();
        try (InputStream in = context.getResources().openRawResource(R.raw.known_models);
             BufferedReader reader = new BufferedReader(
                     new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String text = line.trim();
                if (text.isEmpty() || text.startsWith("#")) {
                    continue;
                }
                // Whole line, line without its hardware version, and every
                // model-looking token inside it ("ADSL RT2860" -> "rt2860").
                // Generic class labels are skipped so "Wireless AP" never
                // becomes a key that matches every access point.
                String whole = compact(text);
                String stem = compact(base(text));
                if (!GENERIC.contains(whole)) {
                    add(out, whole);
                }
                if (!GENERIC.contains(stem)) {
                    add(out, stem);
                }
                for (String token : text.split("\\s+")) {
                    if (hasDigit(token)) {
                        String compactToken = compact(token);
                        if (!GENERIC.contains(compactToken)) {
                            add(out, compactToken);
                        }
                    }
                }
            }
        } catch (Exception ignored) {
            // A broken list must never break a scan; no row is highlighted.
        }
        return out.isEmpty() ? Collections.<String>emptySet() : out;
    }

    private static void add(Set<String> out, String key) {
        if (key.length() >= 3) {
            out.add(key);
        }
    }

    /** Drops a trailing hardware version: "3.0", "v1.0.1", "V3". */
    private static String base(String line) {
        return line.replaceAll("\\s+v?\\d+(\\.\\d+)*$", "").trim();
    }

    private static boolean hasDigit(String value) {
        for (int i = 0; i < value.length(); i++) {
            if (Character.isDigit(value.charAt(i))) {
                return true;
            }
        }
        return false;
    }

    static String compact(String value) {
        if (value == null) {
            return "";
        }
        StringBuilder out = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isLetterOrDigit(c)) {
                out.append(Character.toLowerCase(c));
            }
        }
        return out.toString();
    }
}
