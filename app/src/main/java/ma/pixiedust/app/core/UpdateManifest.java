package ma.pixiedust.app.core;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import ma.pixiedust.app.R;

/**
 * Parsed {@code docs/update.json}: the latest release plus its changelog.
 * The same file is mirrored into {@code res/raw/update_changelog.json} at build
 * time, so "What's new" works offline right after an install.
 */
public final class UpdateManifest {

    public int versionCode;
    public String versionName = "";
    public String url = "";
    public String sha256 = "";
    public long size;
    public final List<Version> versions = new ArrayList<>();

    /** One release block in the changelog. */
    public static final class Version {
        public int versionCode;
        public String versionName = "";
        public String date = "";
        public final List<Line> lines = new ArrayList<>();
    }

    /** One bullet, translated. */
    public static final class Line {
        public String type = "new";
        public String en = "";
        public String fr = "";
    }

    public static UpdateManifest parse(String json) {        if (json == null || json.trim().isEmpty()) {
            return null;
        }
        try {
            JSONObject root = new JSONObject(json);
            UpdateManifest manifest = new UpdateManifest();
            manifest.versionCode = root.optInt("versionCode", 0);
            manifest.versionName = root.optString("versionName", "");
            manifest.url = root.optString("url", "");
            manifest.sha256 = root.optString("sha256", "").toLowerCase(Locale.US);
            manifest.size = root.optLong("size", 0L);

            JSONArray changelog = root.optJSONArray("changelog");
            if (changelog != null) {
                for (int i = 0; i < changelog.length(); i++) {
                    JSONObject node = changelog.optJSONObject(i);
                    if (node == null) {
                        continue;
                    }
                    Version version = new Version();
                    version.versionCode = node.optInt("versionCode", 0);
                    version.versionName = node.optString("versionName", "");
                    version.date = node.optString("date", "");
                    JSONArray items = node.optJSONArray("items");
                    if (items != null) {
                        for (int j = 0; j < items.length(); j++) {
                            JSONObject item = items.optJSONObject(j);
                            if (item == null) {
                                continue;
                            }
                            Line line = new Line();
                            line.type = item.optString("type", "new");
                            line.en = item.optString("en", "");
                            line.fr = item.optString("fr", "");
                            if (!line.en.isEmpty() || !line.fr.isEmpty()) {
                                version.lines.add(line);
                            }
                        }
                    }
                    manifest.versions.add(version);
                }
            }
            return manifest.versionCode > 0 ? manifest : null;
        } catch (Exception ignored) {
            return null;
        }
    }

    /**
     * Changelog that ships inside the APK. Used right after an update when the
     * phone is offline, so "What's new" never depends on the network.
     */
    public static UpdateManifest bundled(Context context) {
        try (InputStream in = context.getResources().openRawResource(R.raw.update_changelog)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            return parse(new String(out.toByteArray(), StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            return null;
        }
    }

    public boolean hasUpdate(int installedCode) {
        return versionCode > installedCode;
    }

    /** Changelog blocks newer than the installed build, newest first. */
    public List<Version> notesAfter(int installedCode, int max) {
        List<Version> out = new ArrayList<>();
        for (Version version : versions) {
            if (version.versionCode <= installedCode) {
                continue;
            }
            out.add(version);
            if (out.size() >= max) {
                break;
            }
        }
        return out;
    }

    public Version version(int code) {
        for (Version version : versions) {
            if (version.versionCode == code) {
                return version;
            }
        }
        return null;
    }
}
