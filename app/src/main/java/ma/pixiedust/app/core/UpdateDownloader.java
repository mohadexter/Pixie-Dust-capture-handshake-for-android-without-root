package ma.pixiedust.app.core;

import android.app.DownloadManager;
import android.content.Context;
import android.net.Uri;
import android.os.Environment;

import java.io.File;

import ma.pixiedust.app.R;

/** Queues the release APK in the app's own external files folder (no storage permission). */
public final class UpdateDownloader {

    private UpdateDownloader() {
    }

    public static File target(Context context, UpdateManifest manifest) {
        String name = manifest.versionName == null || manifest.versionName.isEmpty()
                ? "pixie-" + manifest.versionCode : manifest.versionName;
        return new File(context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS),
                "pixie-" + name + ".apk");
    }

    /** Returns false when the download could not even be queued. */
    public static boolean start(Context context, UpdateManifest manifest) {
        if (manifest == null || manifest.url.isEmpty()) {
            return false;
        }
        if (context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) == null) {
            return false;
        }
        File destination = target(context, manifest);
        if (destination.exists() && !destination.delete()) {
            return false;
        }
        DownloadManager manager =
                (DownloadManager) context.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) {
            return false;
        }
        try {
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(manifest.url))
                    .setTitle(context.getString(R.string.update_download_title, manifest.versionName))
                    .setDescription(context.getString(R.string.update_download_body))
                    .setMimeType("application/vnd.android.package-archive")
                    .setNotificationVisibility(
                            DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    .setDestinationInExternalFilesDir(
                            context, Environment.DIRECTORY_DOWNLOADS, destination.getName());
            long id = manager.enqueue(request);
            new Prefs(context).setPendingUpdate(manifest.sha256,
                    destination.getAbsolutePath(), id);
            return true;
        } catch (Exception ignored) {
            new Prefs(context).clearPendingUpdate();
            return false;
        }
    }
}
