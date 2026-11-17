package ma.pixiedust.app.core;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import ma.pixiedust.app.core.Data.DriverMode;
import ma.pixiedust.app.core.Data.DriverOverride;

/** Small, synchronous preference store (no DataStore, no coroutines). */
public final class Prefs {

    private static final String FILE = "pixie_prefs";

    private static final String K_DISCLAIMER = "disclaimer_accepted";
    private static final String K_SCAN_TIMEOUT = "scan_timeout";
    private static final String K_REFRESH = "refresh_interval";
    private static final String K_KEEP_ON = "keep_screen_on";
    private static final String K_AUTO_REFRESH = "auto_refresh";
    private static final String K_SHOW_ALL = "show_all_networks";
    private static final String K_DEEP = "deep_mode";
    private static final String K_LIVE_VERIFY = "live_verify";
    private static final String K_DRIVER_MODE = "driver_mode";
    private static final String K_CHIPSET = "override_chipset";
    private static final String K_FIRMWARE = "override_firmware";
    private static final String K_VID = "override_vid";
    private static final String K_PID = "override_pid";
    private static final String K_LANGUAGE = "language";
    private static final String K_MIGRATED_V3 = "migrated_v3";
    private static final String K_HANDSHAKE_FOLDER = "handshake_folder";
    private static final String K_HANDSHAKE_TREE = "handshake_tree";
    private static final String K_AP_META = "ap_meta";
    private static final String K_MIGRATED_V5 = "migrated_v5";

    /** Default public folder: Download/Hanshake. */
    public static final String DEFAULT_HANDSHAKE_FOLDER = "Hanshake";

    private final SharedPreferences sp;
    private JSONObject metaCache;

    public Prefs(Context context) {
        sp = context.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
        migrateV3();
        migrateV5();
    }

    /**
     * 1.0.2 shortens the scan to 5 s and turns the candidate filter on. The old
     * release shipped a 25 s default, so a stored 25 is the old default, not a
     * deliberate choice: move it to the new default exactly once.
     */
    private void migrateV3() {
        if (sp.getBoolean(K_MIGRATED_V3, false)) {
            return;
        }
        SharedPreferences.Editor editor = sp.edit().putBoolean(K_MIGRATED_V3, true);
        if (sp.getInt(K_SCAN_TIMEOUT, 25) == 25) {
            editor.putInt(K_SCAN_TIMEOUT, 5);
        }
        editor.apply();
    }

    /**
     * 1.0.5 ships English and French only and stores handshakes in Download/Hanshake.
     * A stored Arabic choice silently falls back to the system language, and the
     * old folder choice becomes the new default exactly once.
     */
    private void migrateV5() {
        if (sp.getBoolean(K_MIGRATED_V5, false)) {
            return;
        }
        SharedPreferences.Editor editor = sp.edit().putBoolean(K_MIGRATED_V5, true);
        if ("ar".equals(sp.getString(K_LANGUAGE, ""))) {
            editor.remove(K_LANGUAGE);
        }
        editor.apply();
    }

    public boolean isDisclaimerAccepted() {
        return sp.getBoolean(K_DISCLAIMER, false);
    }

    public void setDisclaimerAccepted(boolean accepted) {
        sp.edit().putBoolean(K_DISCLAIMER, accepted).apply();
    }

    public int scanTimeout() {
        return clamp(sp.getInt(K_SCAN_TIMEOUT, 5), 5, 60);
    }

    public void setScanTimeout(int seconds) {
        sp.edit().putInt(K_SCAN_TIMEOUT, clamp(seconds, 5, 60)).apply();
    }

    public int refreshInterval() {
        return clamp(sp.getInt(K_REFRESH, 30), 10, 300);
    }

    public void setRefreshInterval(int seconds) {
        sp.edit().putInt(K_REFRESH, clamp(seconds, 10, 300)).apply();
    }

    public boolean keepScreenOn() {
        return sp.getBoolean(K_KEEP_ON, true);
    }

    public void setKeepScreenOn(boolean value) {
        sp.edit().putBoolean(K_KEEP_ON, value).apply();
    }

    public boolean autoRefresh() {
        return sp.getBoolean(K_AUTO_REFRESH, false);
    }

    public void setAutoRefresh(boolean value) {
        sp.edit().putBoolean(K_AUTO_REFRESH, value).apply();
    }

    /** True by default: every network is listed, WPS-capable ones first. */
    public boolean showAllNetworks() {
        return sp.getBoolean(K_SHOW_ALL, true);
    }

    public void setShowAllNetworks(boolean value) {
        sp.edit().putBoolean(K_SHOW_ALL, value).apply();
    }

    public boolean deepMode() {
        return sp.getBoolean(K_DEEP, false);
    }

    public void setDeepMode(boolean value) {
        sp.edit().putBoolean(K_DEEP, value).apply();
    }

    public boolean liveVerify() {
        return sp.getBoolean(K_LIVE_VERIFY, true);
    }

    public void setLiveVerify(boolean value) {
        sp.edit().putBoolean(K_LIVE_VERIFY, value).apply();
    }

    /** Empty means "follow the system"; otherwise an app language tag (en/fr). */
    public String language() {
        String tag = sp.getString(K_LANGUAGE, "");
        return tag == null ? "" : tag;
    }

    public void setLanguage(String tag) {
        if (tag == null || tag.isEmpty()) {
            sp.edit().remove(K_LANGUAGE).apply();
        } else {
            sp.edit().putString(K_LANGUAGE, tag).apply();
        }
    }

    // ------------------------------------------------------- handshake storage

    /** Folder name under Download, e.g. {@code Hanshake}. */
    public String handshakeFolderName() {
        String name = sp.getString(K_HANDSHAKE_FOLDER, DEFAULT_HANDSHAKE_FOLDER);
        name = name == null ? "" : name.trim();
        if (name.isEmpty() || name.contains("/") || name.contains("\\") || name.contains("..")) {
            return DEFAULT_HANDSHAKE_FOLDER;
        }
        return name;
    }

    public void setHandshakeFolderName(String name) {
        if (name == null || name.trim().isEmpty()) {
            sp.edit().remove(K_HANDSHAKE_FOLDER).apply();
        } else {
            sp.edit().putString(K_HANDSHAKE_FOLDER, name.trim()).apply();
        }
    }

    /** Optional SAF tree URI chosen by the user; empty means Download/&lt;folder&gt;. */
    public String handshakeTreeUri() {
        String uri = sp.getString(K_HANDSHAKE_TREE, "");
        return uri == null ? "" : uri;
    }

    public void setHandshakeTreeUri(String uri) {
        if (uri == null || uri.isEmpty()) {
            sp.edit().remove(K_HANDSHAKE_TREE).apply();
        } else {
            sp.edit().putString(K_HANDSHAKE_TREE, uri).apply();
        }
    }

    // ------------------------------------------------------- vendor/model cache

    private JSONObject meta() {
        if (metaCache == null) {
            try {
                metaCache = new JSONObject(sp.getString(K_AP_META, "{}"));
            } catch (Exception ignored) {
                metaCache = new JSONObject();
            }
        }
        return metaCache;
    }

    private String cachedMeta(String bssid, int index) {
        if (bssid == null || bssid.isEmpty()) {
            return "";
        }
        try {
            JSONArray row = meta().optJSONArray(bssid.toUpperCase(java.util.Locale.US));
            return row == null ? "" : row.optString(index, "");
        } catch (Exception ignored) {
            return "";
        }
    }

    public String knownVendor(String bssid) {
        return cachedMeta(bssid, 0);
    }

    public String knownModel(String bssid) {
        return cachedMeta(bssid, 1);
    }

    /**
     * Stores every vendor/model pair found during a scan, so a later scan that
     * misses the WSC information element still shows the same router instead of
     * an empty line. Values are never overwritten with blanks.
     */
    public void rememberApMeta(java.util.Map<String, String[]> rows) {
        if (rows == null || rows.isEmpty()) {
            return;
        }
        try {
            JSONObject all = meta();
            for (java.util.Map.Entry<String, String[]> row : rows.entrySet()) {
                String key = row.getKey() == null
                        ? "" : row.getKey().toUpperCase(java.util.Locale.US);
                String[] value = row.getValue();
                if (key.isEmpty() || value == null) {
                    continue;
                }
                JSONArray existing = all.optJSONArray(key);
                String vendor = value[0] == null ? "" : value[0].trim();
                String model = value[1] == null ? "" : value[1].trim();
                if (existing != null) {
                    if (vendor.isEmpty()) {
                        vendor = existing.optString(0, "");
                    }
                    if (model.isEmpty()) {
                        model = existing.optString(1, "");
                    }
                }
                if (vendor.isEmpty() && model.isEmpty()) {
                    continue;
                }
                all.put(key, new JSONArray().put(vendor).put(model));
            }
            if (all.length() > 600) {
                // Keep the cache bounded without ever losing a fresh entry.
                java.util.Iterator<String> keys = all.keys();
                int remove = all.length() - 600;
                while (keys.hasNext() && remove > 0) {
                    String key = keys.next();
                    if (!rows.containsKey(key) && !rows.containsKey(key.toLowerCase(java.util.Locale.US))) {
                        keys.remove();
                        remove--;
                    }
                }
            }
            sp.edit().putString(K_AP_META, all.toString()).apply();
        } catch (Exception ignored) {
            // A cache write must never break a scan.
        }
    }

    public DriverOverride driverOverride() {
        DriverOverride o = new DriverOverride();
        o.mode = DriverMode.AUTO;
        try {
            o.mode = DriverMode.valueOf(sp.getString(K_DRIVER_MODE, DriverMode.AUTO.name()));
        } catch (IllegalArgumentException ignored) {
            // keep AUTO
        }
        String chipset = sp.getString(K_CHIPSET, null);
        o.chipset = (chipset == null || chipset.isEmpty()) ? null : chipset;
        o.firmwarePath = sp.getString(K_FIRMWARE, null);
        int vid = sp.getInt(K_VID, -1);
        int pid = sp.getInt(K_PID, -1);
        o.vid = vid >= 0 ? vid : null;
        o.pid = pid >= 0 ? pid : null;
        return o;
    }

    public void setChipsetOverride(String chipset) {
        SharedPreferences.Editor e = sp.edit();
        if (chipset == null || chipset.isEmpty()) {
            e.remove(K_CHIPSET).putString(K_DRIVER_MODE, DriverMode.AUTO.name());
        } else {
            e.putString(K_CHIPSET, chipset).putString(K_DRIVER_MODE, DriverMode.MANUAL.name());
        }
        e.apply();
    }

    public void setFirmwareOverride(String path) {
        SharedPreferences.Editor e = sp.edit();
        if (path == null || path.isEmpty()) {
            e.remove(K_FIRMWARE);
        } else {
            e.putString(K_FIRMWARE, path);
        }
        e.apply();
    }

    public void resetDriverOverride() {
        sp.edit()
                .remove(K_CHIPSET)
                .remove(K_FIRMWARE)
                .remove(K_VID)
                .remove(K_PID)
                .putString(K_DRIVER_MODE, DriverMode.AUTO.name())
                .apply();
    }

    private static int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }
}
