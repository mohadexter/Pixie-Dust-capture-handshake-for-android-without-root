package ma.pixiedust.app.ui;

import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.FileProvider;

import java.io.File;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.ApkVerifier;
import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.databinding.ActivityInstallBinding;

/**
 * Last step of the optional update: the APK already passed the download
 * receiver's checks, and it is verified again here before the system installer
 * opens. Never installs silently.
 */
public class InstallActivity extends AppCompatActivity {

    private ActivityInstallBinding b;
    private Prefs prefs;
    private File apk;
    private String sha256 = "";
    private int targetCode;
    private boolean verified;
    private boolean verifying;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityInstallBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);
        prefs = PixieApp.from(this).prefs();

        b.btnBack.setOnClickListener(v -> finish());
        b.btnLater.setOnClickListener(v -> finish());
        b.btnInstall.setOnClickListener(v -> onInstallClick());
        verify();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (verified) {
            refreshInstallButton();
        }
    }

    private void verify() {
        if (verifying) {
            return;
        }
        verifying = true;
        String path = prefs.pendingUpdatePath();
        sha256 = prefs.pendingUpdateSha();
        apk = path == null || path.isEmpty() ? null : new File(path);
        targetCode = archivedVersionCode(apk);
        b.btnInstall.setEnabled(false);
        b.installBody.setText(R.string.install_verifying);
        b.installNote.setVisibility(View.GONE);

        new Thread(() -> {
            ApkVerifier.Result result = ApkVerifier.verify(this, apk, sha256);
            runOnUiThread(() -> showResult(result));
        }, "pixie-verify").start();
    }

    private void showResult(ApkVerifier.Result result) {
        if (isFinishing() || isDestroyed()) {
            return;
        }
        verifying = false;
        if (result == ApkVerifier.Result.OK) {
            verified = true;
            b.installTitle.setText(R.string.install_ready_title);
            b.installBody.setText(getString(R.string.install_ready_body, versionName()));
            b.installNote.setText(apk.getName() + "\nSHA-256 " + shortHash());
            b.installNote.setVisibility(View.VISIBLE);
            refreshInstallButton();
            return;
        }

        verified = false;
        b.btnInstall.setEnabled(false);
        b.installTitle.setText(R.string.install_title);
        b.installNote.setVisibility(View.GONE);
        if (result == ApkVerifier.Result.MISSING) {
            b.installBody.setText(R.string.install_missing);
        } else if (result == ApkVerifier.Result.HASH) {
            b.installBody.setText(R.string.install_hash);
        } else if (result == ApkVerifier.Result.SIGNATURE) {
            b.installBody.setText(R.string.install_signature);
        } else {
            b.installBody.setText(R.string.install_error);
        }
        prefs.clearPendingUpdate();
        if (apk != null && apk.isFile() && result != ApkVerifier.Result.MISSING) {
            //noinspection ResultOfMethodCallIgnored
            apk.delete();
        }
    }

    private void refreshInstallButton() {
        if (canInstall()) {
            b.btnInstall.setText(R.string.install_install);
            b.btnInstall.setEnabled(true);
            b.installNote.setVisibility(View.VISIBLE);
            b.installBody.setText(getString(R.string.install_ready_body, versionName()));
        } else {
            b.btnInstall.setText(R.string.install_allow);
            b.btnInstall.setEnabled(true);
            b.installBody.setText(R.string.install_unknown_sources);
            b.installNote.setVisibility(View.GONE);
        }
    }

    private void onInstallClick() {
        if (!verified) {
            return;
        }
        if (!canInstall()) {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception ignored) {
                Toast.makeText(this, R.string.install_failed_to_open, Toast.LENGTH_LONG).show();
            }
            return;
        }
        try {
            Uri uri = FileProvider.getUriForFile(this,
                    getPackageName() + ".fileprovider", apk);
            if (targetCode > 0) {
                prefs.setPendingWhatsNew(targetCode);
            }
            Intent install = new Intent(Intent.ACTION_VIEW)
                    .setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(install);
        } catch (Exception ignored) {
            Toast.makeText(this, R.string.install_failed_to_open, Toast.LENGTH_LONG).show();
        }
    }

    private boolean canInstall() {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.O
                || getPackageManager().canRequestPackageInstalls();
    }

    private String versionName() {
        try {
            PackageInfo info = getPackageManager()
                    .getPackageArchiveInfo(apk.getAbsolutePath(), 0);
            if (info != null && info.versionName != null) {
                return info.versionName;
            }
        } catch (Exception ignored) {
            // Fall through to the file name.
        }
        return apk == null ? "" : apk.getName();
    }

    private int archivedVersionCode(File file) {
        if (file == null) {
            return 0;
        }
        try {
            PackageInfo info = getPackageManager()
                    .getPackageArchiveInfo(file.getAbsolutePath(), 0);
            return info == null ? 0
                    : (int) ((Build.VERSION.SDK_INT >= 28
                    ? info.getLongVersionCode() : info.versionCode) & 0x7fffffffL);
        } catch (Exception ignored) {
            return 0;
        }
    }

    private String shortHash() {
        return sha256.length() > 16
                ? sha256.substring(0, 16) + "…" : sha256;
    }
}
