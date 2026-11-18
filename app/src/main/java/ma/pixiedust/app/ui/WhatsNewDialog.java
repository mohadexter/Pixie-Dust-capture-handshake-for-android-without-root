package ma.pixiedust.app.ui;

import android.app.Activity;
import android.content.Context;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import java.util.Collections;
import java.util.List;
import java.util.Locale;

import ma.pixiedust.app.R;
import ma.pixiedust.app.core.UpdateChecker;
import ma.pixiedust.app.core.UpdateManifest;

/**
 * "What's new" shown in three places: before an update, on the first launch
 * after an update (offline, from the changelog bundled in the APK), and from
 * About. It is always dismissible and never blocks the app.
 */
public final class WhatsNewDialog {

    private WhatsNewDialog() {
    }

    /** Notes for one exact version, from the cache or the bundled mirror. */
    public static void showForVersion(Activity activity, int versionCode) {
        UpdateManifest manifest = manifest(activity);
        UpdateManifest.Version version = manifest == null ? null : manifest.version(versionCode);
        if (version == null) {
            Toast.makeText(activity, R.string.update_no_notes, Toast.LENGTH_SHORT).show();
            return;
        }
        dialog(activity,
                activity.getString(R.string.update_notes_title, version.versionName),
                Collections.singletonList(version));
    }

    /** Every release newer than the installed build, newest first. */
    public static void showAfter(Activity activity, UpdateManifest manifest, int installedCode) {
        if (manifest == null) {
            return;
        }
        dialog(activity,
                activity.getString(R.string.update_notes_title, manifest.versionName),
                manifest.notesAfter(installedCode, 3));
    }

    /** Full changelog, reached from About. */
    public static void showReleaseNotes(Activity activity) {
        UpdateManifest manifest = manifest(activity);
        if (manifest == null) {
            Toast.makeText(activity, R.string.update_no_notes, Toast.LENGTH_SHORT).show();
            return;
        }
        dialog(activity, activity.getString(R.string.update_notes_all), manifest.versions);
    }

    private static UpdateManifest manifest(Context context) {
        UpdateManifest manifest = UpdateChecker.cached(context);
        if (manifest == null) {
            manifest = UpdateManifest.bundled(context);
        }
        return manifest;
    }

    private static void dialog(Activity activity, String title, List<UpdateManifest.Version> blocks) {
        ScrollView scroll = new ScrollView(activity);
        scroll.setClipToPadding(false);
        int pad = dp(activity, 20);
        scroll.setPadding(pad, dp(activity, 4), pad, 0);

        LinearLayout list = new LinearLayout(activity);
        list.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(list);

        boolean french = Locale.getDefault().getLanguage().startsWith("fr");
        if (blocks == null || blocks.isEmpty()) {
            list.addView(body(activity, activity.getString(R.string.update_no_notes)));
        } else {
            for (UpdateManifest.Version block : blocks) {
                TextView header = new TextView(activity);
                header.setTextAppearance(R.style.TextAppearance_PixieDust_Section);
                header.setText(block.date.isEmpty()
                        ? block.versionName : block.versionName + "  ·  " + block.date);
                LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT);
                params.topMargin = dp(activity, 12);
                list.addView(header, params);
                for (UpdateManifest.Line line : block.lines) {
                    String text = french ? line.fr : line.en;
                    if (text.isEmpty()) {
                        text = french ? line.en : line.fr;
                    }
                    if (text.isEmpty()) {
                        continue;
                    }
                    list.addView(body(activity,
                            typeLabel(activity, line.type) + "  ·  " + text));
                }
            }
        }

        new MaterialAlertDialogBuilder(activity)
                .setTitle(title)
                .setView(scroll)
                .setPositiveButton(R.string.generic_close, null)
                .show();
    }

    private static String typeLabel(Context context, String type) {
        int res;
        if ("fix".equals(type)) {
            res = R.string.update_type_fix;
        } else if ("improvement".equals(type) || "improved".equals(type)) {
            res = R.string.update_type_improvement;
        } else {
            res = R.string.update_type_new;
        }
        return context.getString(res);
    }

    private static TextView body(Context context, String text) {
        TextView view = new TextView(context);
        view.setTextAppearance(R.style.TextAppearance_PixieDust_Body);
        view.setTextColor(context.getColor(R.color.ink_soft));
        view.setText(text);
        view.setPadding(0, dp(context, 4), 0, 0);
        view.setLineSpacing(dp(context, 2), 1f);
        return view;
    }

    private static int dp(Context context, int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }
}
