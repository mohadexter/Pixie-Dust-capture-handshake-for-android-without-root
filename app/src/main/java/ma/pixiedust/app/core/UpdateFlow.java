package ma.pixiedust.app.core;

import android.app.Activity;
import android.content.pm.PackageInfo;
import android.os.Build;
import android.widget.Toast;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import ma.pixiedust.app.R;
import ma.pixiedust.app.ui.WhatsNewDialog;

/**
 * Glue for the optional update channel. It never blocks a scan, never forces an
 * install, and keeps working offline: a failed check simply says nothing.
 */
public final class UpdateFlow {

    private static boolean dialogShowing;

    private UpdateFlow() {
    }

    /** Called once per launch from the scan screen, after the disclaimer. */
    public static void onLaunch(Activity activity) {
        Prefs prefs = new Prefs(activity);
        UpdateNotifier.ensureChannel(activity);
        int current = versionCode(activity);
        int seen = prefs.seenVersion();

        if (prefs.pendingWhatsNew() == current) {
            // The in-app updater installed this build: show its notes even offline.
            prefs.clearPendingWhatsNew();
            prefs.setSeenVersion(current);
            WhatsNewDialog.showForVersion(activity, current);
        } else if (seen > 0 && seen < current) {
            // Updated by hand (APK from the release page): same offline notes.
            prefs.setSeenVersion(current);
            WhatsNewDialog.showForVersion(activity, current);
        } else if (seen == 0) {
            // First install: there is no "previous version" to compare with.
            prefs.setSeenVersion(current);
        }

        check(activity, false, false);
    }

    /** About > Check for updates: always talks to GitHub and always answers. */
    public static void checkManually(Activity activity) {
        Toast.makeText(activity, R.string.update_checking, Toast.LENGTH_SHORT).show();
        check(activity, true, true);
    }

    public static int versionCode(Activity activity) {
        try {
            PackageInfo info = activity.getPackageManager()
                    .getPackageInfo(activity.getPackageName(), 0);
            return (int) ((Build.VERSION.SDK_INT >= 28
                    ? info.getLongVersionCode() : info.versionCode) & 0x7fffffffL);
        } catch (Exception ignored) {
            return 0;
        }
    }

    private static void check(Activity activity, boolean force, boolean interactive) {
        UpdateChecker.checkAsync(activity, force, manifest -> {
            if (activity.isFinishing() || activity.isDestroyed()) {
                return;
            }
            int current = versionCode(activity);
            if (manifest == null) {
                if (interactive) {
                    Toast.makeText(activity, R.string.update_check_failed,
                            Toast.LENGTH_LONG).show();
                }
                return;
            }
            if (!manifest.hasUpdate(current)) {
                if (interactive) {
                    Toast.makeText(activity, R.string.update_check_current,
                            Toast.LENGTH_SHORT).show();
                }
                return;
            }
            Prefs prefs = new Prefs(activity);
            if (!interactive && prefs.dismissedUpdate() >= manifest.versionCode) {
                return;
            }
            UpdateNotifier.available(activity, manifest);
            showAvailable(activity, manifest, current);
        });
    }

    private static void showAvailable(Activity activity,
                                      UpdateManifest manifest,
                                      int current) {
        if (dialogShowing) {
            return;
        }
        dialogShowing = true;
        String installed = installedName(activity);
        new MaterialAlertDialogBuilder(activity)
                .setTitle(R.string.update_title)
                .setMessage(activity.getString(R.string.update_body,
                        manifest.versionName, installed))
                .setNeutralButton(R.string.update_whats_new,
                        (dialog, which) -> WhatsNewDialog.showAfter(activity, manifest, current))
                .setNegativeButton(R.string.update_later, (dialog, which) ->
                        new Prefs(activity).dismissUpdate(manifest.versionCode))
                .setPositiveButton(R.string.update_download, (dialog, which) -> {
                    if (UpdateDownloader.start(activity, manifest)) {
                        Toast.makeText(activity, R.string.update_download_queued,
                                Toast.LENGTH_LONG).show();
                    } else {
                        Toast.makeText(activity, R.string.update_download_failed,
                                Toast.LENGTH_LONG).show();
                    }
                })
                .setOnDismissListener(dialog -> dialogShowing = false)
                .show();
    }

    private static String installedName(Activity activity) {
        try {
            PackageInfo info = activity.getPackageManager()
                    .getPackageInfo(activity.getPackageName(), 0);
            return info.versionName == null ? "" : info.versionName;
        } catch (Exception ignored) {
            return "";
        }
    }
}
