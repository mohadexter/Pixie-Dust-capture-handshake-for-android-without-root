package ma.pixiedust.app.core;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Reads {@code docs/update.json} from the project's GitHub page, at most once a
 * day unless the user asks explicitly. Everything is optional: a failed request
 * leaves the app untouched, and the last good answer stays cached on disk.
 */
public final class UpdateChecker {

    public static final String MANIFEST_URL = "https://raw.githubusercontent.com/"
            + "mohadexter/Pixie-Dust-capture-handshake-for-android-without-root/"
            + "main/docs/update.json";

    private static final long DAY_MS = 24L * 60L * 60L * 1000L;
    private static final int TIMEOUT_MS = 6000;

    public interface Callback {
        void onResult(UpdateManifest manifest);
    }

    private UpdateChecker() {
    }

    /** Last successful answer, without touching the network. May be null. */
    public static UpdateManifest cached(Context context) {
        return UpdateManifest.parse(new Prefs(context).cachedUpdate());
    }

    public static void checkAsync(Context context, boolean force, Callback callback) {
        Context app = context.getApplicationContext();
        Prefs prefs = new Prefs(app);
        UpdateManifest cached = UpdateManifest.parse(prefs.cachedUpdate());
        long age = System.currentTimeMillis() - prefs.updateCheckedAt();
        if (!force && cached != null && age < DAY_MS) {
            deliver(callback, cached);
            return;
        }
        new Thread(() -> {
            String body = null;
            try {
                body = download();
            } catch (Exception ignored) {
                // Offline, DNS failure, GitHub down: keep the cached answer.
            }
            UpdateManifest fresh = UpdateManifest.parse(body);
            if (fresh != null) {
                prefs.setCachedUpdate(body);
                prefs.setUpdateCheckedAt(System.currentTimeMillis());
            }
            deliver(callback, fresh != null ? fresh : cached);
        }, "pixie-update").start();
    }

    private static String download() throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(MANIFEST_URL).openConnection();
        connection.setConnectTimeout(TIMEOUT_MS);
        connection.setReadTimeout(TIMEOUT_MS);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("Accept", "application/json");
        try (InputStream in = connection.getInputStream()) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        } finally {
            connection.disconnect();
        }
    }

    private static void deliver(Callback callback, UpdateManifest manifest) {
        if (callback == null) {
            return;
        }
        new Handler(Looper.getMainLooper()).post(() -> callback.onResult(manifest));
    }
}
