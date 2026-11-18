package ma.pixiedust.app.core;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import ma.pixiedust.app.R;
import ma.pixiedust.app.ui.InstallActivity;
import ma.pixiedust.app.ui.ScanActivity;

/** Low-priority notifications for the optional update channel. */
public final class UpdateNotifier {

    public static final String CHANNEL = "pixie_update";

    private static final int ID_AVAILABLE = 41;
    private static final int ID_READY = 42;
    private static final int ID_FAILED = 43;

    private UpdateNotifier() {
    }

    public static void ensureChannel(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager =
                (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null || manager.getNotificationChannel(CHANNEL) != null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL,
                context.getString(R.string.update_channel_name),
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(context.getString(R.string.update_channel_name));
        manager.createNotificationChannel(channel);
    }

    public static void available(Context context, UpdateManifest manifest) {
        Intent open = new Intent(context, ScanActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent tap = PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_download)
                .setContentTitle(context.getString(R.string.update_note_title, manifest.versionName))
                .setContentText(context.getString(R.string.update_note_text))
                .setStyle(new NotificationCompat.BigTextStyle()
                        .bigText(context.getString(R.string.update_note_text)))
                .setContentIntent(tap)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_LOW);
        post(context, ID_AVAILABLE, builder);
    }

    /** The verified APK is on disk: one tap opens the system installer. */
    public static void ready(Context context) {
        Intent install = new Intent(context, InstallActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent tap = PendingIntent.getActivity(context, 1, install,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_download)
                .setContentTitle(context.getString(R.string.update_ready_title))
                .setContentText(context.getString(R.string.update_ready_text))
                .setContentIntent(tap)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT);
        post(context, ID_READY, builder);
    }

    public static void failed(Context context) {
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_warning)
                .setContentTitle(context.getString(R.string.update_failed_title))
                .setContentText(context.getString(R.string.update_failed_text))
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_LOW);
        post(context, ID_FAILED, builder);
    }

    private static void post(Context context,
                             int id,
                             NotificationCompat.Builder builder) {
        ensureChannel(context);
        try {
            NotificationManagerCompat manager = NotificationManagerCompat.from(context);
            if (!manager.areNotificationsEnabled()) {
                return;
            }
            manager.notify(id, builder.build());
        } catch (Exception ignored) {
            // A refused notification must never break the caller.
        }
    }
}
