package ma.pixiedust.app.core;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * App-private history of what the user already captured or recovered.
 *
 * <p>Two kinds of entries are kept:
 * <ul>
 *   <li>{@code handshake} — a WPA 4-way pcap that passed wifit3's crackability
 *       check and was really written to disk;</li>
 *   <li>{@code credentials} — a network for which a WPS PIN and/or the Wi-Fi
 *       password was recovered.</li>
 * </ul>
 *
 * <p>Nothing leaves the phone: this is a private SharedPreferences file, and the
 * app has no INTERNET permission. Only the handful of fields shown on the
 * history screen are stored.
 */
public final class HistoryStore {

    public static final String TYPE_HANDSHAKE = "handshake";
    public static final String TYPE_CREDENTIALS = "credentials";

    private static final String FILE = "pixie_history";
    private static final String KEY_ENTRIES = "entries";
    private static final int MAX_ENTRIES = 200;

    /** One row on the history screen. */
    public static final class Entry {
        public String type = TYPE_HANDSHAKE;
        public String ssid = "";
        public String bssid = "";
        public String vendor = "";
        public String model = "";
        public String path = "";
        public String pin = "";
        public String psk = "";
        public int channel;
        public long timestamp;
        public int frames;
        public int clients;
        public boolean complete;

        public boolean isHandshake() {
            return TYPE_HANDSHAKE.equals(type);
        }
    }

    private final SharedPreferences sp;

    public HistoryStore(Context context) {
        sp = context.getApplicationContext()
                .getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public synchronized List<Entry> all() {
        List<Entry> out = new ArrayList<>();
        try {
            JSONArray array = new JSONArray(sp.getString(KEY_ENTRIES, "[]"));
            for (int i = 0; i < array.length(); i++) {
                JSONObject o = array.optJSONObject(i);
                if (o == null) {
                    continue;
                }
                Entry e = new Entry();
                e.type = o.optString("type", TYPE_HANDSHAKE);
                e.ssid = o.optString("ssid", "");
                e.bssid = o.optString("bssid", "");
                e.vendor = o.optString("vendor", "");
                e.model = o.optString("model", "");
                e.path = o.optString("path", "");
                e.pin = o.optString("pin", "");
                e.psk = o.optString("psk", "");
                e.channel = o.optInt("channel", 0);
                e.timestamp = o.optLong("timestamp", 0L);
                e.frames = o.optInt("frames", 0);
                e.clients = o.optInt("clients", 0);
                e.complete = o.optBoolean("complete", false);
                out.add(e);
            }
        } catch (Exception ignored) {
            // A corrupted history must never break the app; show an empty list.
        }
        Collections.sort(out, (a, b) -> Long.compare(b.timestamp, a.timestamp));
        return out;
    }

    public synchronized void add(Entry entry) {
        if (entry == null) {
            return;
        }
        if (entry.timestamp <= 0L) {
            entry.timestamp = System.currentTimeMillis();
        }
        List<Entry> entries = all();
        // De-duplicate: same kind of result on the same network replaces the old
        // row instead of filling the list with duplicates from repeated runs.
        for (int i = entries.size() - 1; i >= 0; i--) {
            Entry old = entries.get(i);
            boolean same = entry.type.equals(old.type)
                    && entry.bssid.equalsIgnoreCase(old.bssid);
            if (same && TYPE_HANDSHAKE.equals(entry.type)) {
                same = entry.path.equals(old.path);
            } else if (same) {
                same = entry.pin.equals(old.pin) && entry.psk.equals(old.psk);
            }
            if (same) {
                entries.remove(i);
            }
        }
        entries.add(0, entry);
        while (entries.size() > MAX_ENTRIES) {
            entries.remove(entries.size() - 1);
        }
        write(entries);
    }

    public synchronized void clear() {
        sp.edit().remove(KEY_ENTRIES).apply();
    }

    private void write(List<Entry> entries) {
        JSONArray array = new JSONArray();
        for (Entry e : entries) {
            try {
                JSONObject o = new JSONObject();
                o.put("type", e.type);
                o.put("ssid", e.ssid);
                o.put("bssid", e.bssid);
                o.put("vendor", e.vendor);
                o.put("model", e.model);
                o.put("path", e.path);
                o.put("pin", e.pin);
                o.put("psk", e.psk);
                o.put("channel", e.channel);
                o.put("timestamp", e.timestamp);
                o.put("frames", e.frames);
                o.put("clients", e.clients);
                o.put("complete", e.complete);
                array.put(o);
            } catch (Exception ignored) {
                // skip this row, keep the rest
            }
        }
        sp.edit().putString(KEY_ENTRIES, array.toString()).apply();
    }
}
