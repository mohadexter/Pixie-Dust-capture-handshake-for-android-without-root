package ma.pixiedust.app.core;

import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;

import java.io.File;

/**
 * Receives DownloadManager's completion broadcast, verifies the APK against the
 * published SHA-256 and the installed signing certificate, then says it is ready.
 * A bad download is discarded; the installed app is never touched.
 */
public class UpdateReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null
                || !DownloadManager.ACTION_DOWNLOAD_COMPLETE.equals(intent.getAction())) {
            return;
        }
        long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L);
        if (id < 0) {
            return;
        }
        Prefs prefs = new Prefs(context);
        String path = prefs.pendingUpdatePath();
        if (path == null || path.isEmpty() || prefs.pendingUpdateId() != id) {
            return;
        }

        DownloadManager manager =
                (DownloadManager) context.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) {
            return;
        }
        int status = -1;
        try (Cursor cursor = manager.query(new DownloadManager.Query().setFilterById(id))) {
            if (cursor != null && cursor.moveToFirst()) {
                status = cursor.getInt(cursor.getColumnIndexOrThrow(
                        DownloadManager.COLUMN_STATUS));
            }
        } catch (Exception ignored) {
            status = -1;
        }

        if (status != DownloadManager.STATUS_SUCCESSFUL) {
            prefs.clearPendingUpdate();
            UpdateNotifier.failed(context);
            return;
        }

        File apk = new File(path);
        ApkVerifier.Result result = ApkVerifier.verify(context, apk, prefs.pendingUpdateSha());
        if (result == ApkVerifier.Result.OK) {
            UpdateNotifier.ready(context);
            return;
        }

        prefs.clearPendingUpdate();
        // Do not leave an unverified installer on disk.
        //noinspection ResultOfMethodCallIgnored
        apk.delete();
        UpdateNotifier.failed(context);
    }
}
