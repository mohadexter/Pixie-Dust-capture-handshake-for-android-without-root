package ma.pixiedust.app.ui;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.view.View;
import android.view.Window;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.OvershootInterpolator;
import android.widget.Toast;

import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;

import java.io.File;

import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;

/** Small shared UI helpers (no third-party libraries). */
public final class Ui {

    private Ui() {
    }

    public static float dp(Context context, float value) {
        return value * context.getResources().getDisplayMetrics().density;
    }

    /** Paper background behind the status/navigation bars, dark icons on it. */
    @SuppressWarnings("deprecation")
    public static void paintSystemBars(Activity activity) {
        Window window = activity.getWindow();
        int paper = ContextCompat.getColor(activity, R.color.paper);
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            window.setStatusBarColor(paper);
            window.setNavigationBarColor(paper);
        }
        View decor = window.getDecorView();
        int flags = decor.getSystemUiVisibility();
        flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        }
        decor.setSystemUiVisibility(flags);
    }

    public static void toast(Context context, int messageRes) {
        Toast.makeText(context, messageRes, Toast.LENGTH_SHORT).show();
    }

    public static void toast(Context context, String message) {
        Toast.makeText(context, message, Toast.LENGTH_SHORT).show();
    }

    /** Explicit user action: copies to the clipboard, never to disk. */
    public static void copy(Context context, String value) {
        copy(context, value, R.string.result_copied);
    }

    public static void copy(Context context, String value, int toastRes) {
        if (value == null || value.trim().isEmpty()) {
            return;
        }
        ClipboardManager manager =
                (ClipboardManager) context.getSystemService(Context.CLIPBOARD_SERVICE);
        if (manager == null) {
            return;
        }
        manager.setPrimaryClip(ClipData.newPlainText("pixie", value));
        toast(context, toastRes);
    }

    public static String band(Context context, int channel) {
        return context.getString(channel > 14 ? R.string.details_band_5 : R.string.details_band_24);
    }

    public static int signalLevel(int rssi) {
        if (rssi >= -55) {
            return 4;
        }
        if (rssi >= -66) {
            return 3;
        }
        if (rssi >= -77) {
            return 2;
        }
        return 1;
    }

    /**
     * The PIN is shown as one unbroken run of digits (like the WPS label on the
     * router): "12345678", never "1234 5678". Copying uses the same value.
     */
    public static String pinGroups(String pin) {
        if (pin == null) {
            return "";
        }
        return pin.replaceAll("\\s+", "");
    }

    /**
     * Short "extraction" animation: the digits/characters churn for a moment, then
     * settle on the real value. Runs once, after the engine has produced the value,
     * so nothing fake is ever displayed as a result.
     */
    public static void revealDecoding(final android.widget.TextView view, final String value) {
        if (view == null) {
            return;
        }
        if (value == null || value.isEmpty()) {
            view.setText("");
            return;
        }
        final android.os.Handler handler = new android.os.Handler(android.os.Looper.getMainLooper());
        final android.graphics.Typeface face = view.getTypeface();
        final java.util.Random random = new java.util.Random();
        final char[] pool = "0123456789ABCDEF".toCharArray();
        final long end = android.os.SystemClock.uptimeMillis() + 750L;
        view.setAlpha(0.72f);
        Runnable tick = new Runnable() {
            @Override
            public void run() {
                long now = android.os.SystemClock.uptimeMillis();
                if (now >= end) {
                    view.setText(value);
                    view.setAlpha(1f);
                    view.setTypeface(face);
                    revealSecret(view);
                    return;
                }
                StringBuilder fake = new StringBuilder(value.length());
                for (int i = 0; i < value.length(); i++) {
                    char real = value.charAt(i);
                    fake.append(Character.isLetterOrDigit(real)
                            ? pool[random.nextInt(pool.length)]
                            : real);
                }
                view.setText(fake.toString());
                handler.postDelayed(this, 55L);
            }
        };
        handler.post(tick);
    }

    public static String orDash(String value) {
        return value == null || value.trim().isEmpty() ? "\u2014" : value;
    }

    /**
     * Opens a saved capture with whatever app handles pcap files. A file written
     * through a folder the user picked is opened by its content URI; a file in
     * Download/&lt;folder&gt; goes through our FileProvider. Returns false when no
     * app can take it, so the caller can fall back to copying the path instead of
     * pretending it opened.
     */
    public static boolean openDocument(Activity activity, String uriString,
                                       String filePath, String mime) {
        if (activity == null) {
            return false;
        }
        try {
            Uri uri;
            if (uriString != null && !uriString.trim().isEmpty()) {
                uri = Uri.parse(uriString);
            } else {
                if (filePath == null || filePath.trim().isEmpty()) {
                    return false;
                }
                File file = new File(filePath);
                if (!file.isFile()) {
                    return false;
                }
                uri = FileProvider.getUriForFile(activity,
                        activity.getPackageName() + ".fileprovider", file);
            }
            Intent view = new Intent(Intent.ACTION_VIEW);
            view.setDataAndType(uri, mime);
            view.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            activity.startActivity(view);
            return true;
        } catch (Exception ignored) {
            // No viewer, or the provider refused: the caller copies the path.
            return false;
        }
    }

    // ------------------------------------------------------------- animation

    /** Fade plus a small rise: a card or a row that has just appeared. */
    public static void enter(View view) {
        if (view == null) {
            return;
        }
        view.setAlpha(0f);
        view.setTranslationY(dp(view.getContext(), 10f));
        view.animate()
                .alpha(1f)
                .translationY(0f)
                .setDuration(320L)
                .setInterpolator(new DecelerateInterpolator())
                .start();
    }

    /** Pop plus fade for a recovered secret; deliberately short and once only. */
    public static void revealSecret(View view) {
        if (view == null) {
            return;
        }
        view.setAlpha(0f);
        view.setScaleX(0.92f);
        view.setScaleY(0.92f);
        view.setTranslationY(dp(view.getContext(), 8f));
        view.animate()
                .alpha(1f)
                .scaleX(1f)
                .scaleY(1f)
                .translationY(0f)
                .setDuration(460L)
                .setInterpolator(new OvershootInterpolator(1.1f))
                .start();
    }

    /** Fade a view out, then remove it from the layout. */
    /**
     * Two short pulses: the physical confirmation that an operation really
     * succeeded (PIN/PSK recovered, handshake saved). Silent no-op when the phone
     * has no vibrator or the system blocks it.
     */
    public static void vibrateSuccess(Context context) {
        try {
            android.os.Vibrator vibrator;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                android.os.VibratorManager manager =
                        (android.os.VibratorManager) context.getSystemService(
                                Context.VIBRATOR_MANAGER_SERVICE);
                vibrator = manager == null ? null : manager.getDefaultVibrator();
            } else {
                //noinspection deprecation
                vibrator = (android.os.Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
            }
            if (vibrator == null || !vibrator.hasVibrator()) {
                return;
            }
            long[] pattern = {0L, 45L, 70L, 130L};
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(android.os.VibrationEffect.createWaveform(pattern, -1));
            } else {
                //noinspection deprecation
                vibrator.vibrate(pattern, -1);
            }
        } catch (Exception ignored) {
            // vibration is cosmetic: never let it break a result screen
        }
    }

    public static void fadeOut(View view) {        if (view == null || view.getVisibility() != View.VISIBLE) {
            return;
        }
        view.animate()
                .alpha(0f)
                .setDuration(180L)
                .withEndAction(() -> {
                    view.setVisibility(View.GONE);
                    view.setAlpha(1f);
                })
                .start();
    }

    // ------------------------------------------------------------- navigation

    public static void putAp(Intent intent, Data.AccessPoint ap) {
        if (ap == null) {
            return;
        }
        intent.putExtra("ap_bssid", ap.bssid);
        intent.putExtra("ap_ssid", ap.ssid);
        intent.putExtra("ap_channel", ap.channel);
        intent.putExtra("ap_rssi", ap.rssi);
        intent.putExtra("ap_encryption", ap.encryption);
        intent.putExtra("ap_wps", ap.wps);
        intent.putExtra("ap_wps_version", ap.wpsVersion);
        intent.putExtra("ap_locked", ap.locked);
        intent.putExtra("ap_vendor", ap.vendor);
        intent.putExtra("ap_model", ap.model);
        intent.putExtra("ap_clients", ap.clients);
    }

    public static Data.AccessPoint getAp(Intent intent) {
        if (intent == null || !intent.hasExtra("ap_bssid")) {
            return null;
        }
        Data.AccessPoint ap = new Data.AccessPoint();
        ap.bssid = safe(intent.getStringExtra("ap_bssid"));
        ap.ssid = safe(intent.getStringExtra("ap_ssid"));
        ap.channel = intent.getIntExtra("ap_channel", 0);
        ap.rssi = intent.getIntExtra("ap_rssi", -70);
        ap.encryption = safe(intent.getStringExtra("ap_encryption"));
        ap.wps = intent.getBooleanExtra("ap_wps", false);
        ap.wpsVersion = safe(intent.getStringExtra("ap_wps_version"));
        ap.locked = intent.getBooleanExtra("ap_locked", false);
        ap.vendor = safe(intent.getStringExtra("ap_vendor"));
        ap.model = safe(intent.getStringExtra("ap_model"));
        ap.clients = intent.getIntExtra("ap_clients", 0);
        return ap;
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }
}
