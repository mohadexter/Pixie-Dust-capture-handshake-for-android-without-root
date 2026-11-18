package ma.pixiedust.app.ui;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.hardware.usb.UsbDevice;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;

import java.util.List;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.PixieError;
import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.core.UpdateFlow;
import ma.pixiedust.app.databinding.ActivityScanBinding;
import ma.pixiedust.app.usb.UsbOtg;

/** The only entry point: adapter state, live scan list, error card. */
public class ScanActivity extends AppCompatActivity implements Repo.Listener {

    private ActivityScanBinding b;
    private Repo repo;
    private Prefs prefs;
    private UsbOtg usb;
    private ApAdapter adapter;
    private boolean disclaimerLaunched;
    private boolean updatesChecked;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityScanBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        PixieApp app = PixieApp.from(this);
        repo = app.repo();
        prefs = app.prefs();
        usb = app.usb();

        adapter = new ApAdapter(this, this::openDetails);
        b.list.setLayoutManager(new LinearLayoutManager(this));
        b.list.setAdapter(adapter);
        b.list.setHasFixedSize(true);

        b.btnScan.setOnClickListener(v -> repo.triggerScan(true));
        b.btnRetry.setOnClickListener(v -> {
            repo.clearError();
            repo.triggerScan(true);
        });
        b.btnDrivers.setOnClickListener(v -> startActivity(new Intent(this, DriversActivity.class)));
        b.btnHistory.setOnClickListener(v -> startActivity(new Intent(this, HistoryActivity.class)));
        b.btnSettings.setOnClickListener(v -> startActivity(new Intent(this, SettingsActivity.class)));
        b.btnSupport.setOnClickListener(v -> {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW,
                        Uri.parse("https://t.me/PixieDustapp")));
            } catch (Exception ignored) {
                Ui.toast(this, R.string.support_no_browser);
            }
        });

        askForNotificationPermission();
        handleIntent(getIntent());
    }

    @Override
    protected void onResume() {
        super.onResume();
        repo.addListener(this);
        repo.setForeground(true);
        if (!prefs.isDisclaimerAccepted()) {
            if (!disclaimerLaunched) {
                disclaimerLaunched = true;
                startActivity(new Intent(this, DisclaimerActivity.class));
            }
        } else {
            disclaimerLaunched = false;
            autoScanIfReady();
            if (!updatesChecked) {
                updatesChecked = true;
                UpdateFlow.onLaunch(this);
            }
        }
        render();
    }

    @Override
    protected void onPause() {
        repo.setForeground(false);
        repo.removeListener(this);
        // A fresh foreground visit is a fresh (silent) update check.
        updatesChecked = false;
        super.onPause();
    }

    @Override
    protected void onNewIntent(@NonNull Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent != null && intent.getBooleanExtra("rescan", false)) {
            repo.triggerScan(true);
            intent.removeExtra("rescan");
        }
    }

    /**
     * Notifications carry capture progress and the optional update notice. Ask
     * once on Android 13+; a refusal is respected and nothing else changes.
     */
    private void askForNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33 || prefs.notificationAsked()) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        prefs.setNotificationAsked();
        requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 21);
    }

    /** Opens the adapter without asking for permission, only when one is already granted. */
    private void autoScanIfReady() {
        if (repo.scanning || repo.attacking || repo.capturing || !repo.accessPoints.isEmpty()) {
            return;
        }
        UsbDevice device = usb.findAttached();
        if (device != null && usb.hasPermission(device)) {
            repo.triggerScan(false);
        }
    }

    private void openDetails(Data.AccessPoint ap) {
        NetworkSheet.show(this, ap);
    }

    @Override
    public void onState() {
        render();
    }

    private void render() {
        if (b == null) {
            return;
        }
        List<Data.AccessPoint> accessPoints = repo.accessPoints;

        b.subtitleText.setText(accessPoints.isEmpty()
                ? getString(R.string.scan_count_zero)
                : getString(R.string.scan_count_many, accessPoints.size()));

        Data.UsbAdapter device = repo.currentAdapter();
        if (!repo.adapterDescription.isEmpty()) {
            b.adapterText.setText(getString(R.string.scan_adapter_named, repo.adapterDescription));
        } else if (device != null && device.supported) {
            b.adapterText.setText(getString(R.string.scan_adapter_named, device.productName));
        } else {
            b.adapterText.setText(R.string.scan_adapter_none);
        }

        if (repo.scanning) {
            b.countdownText.setText(R.string.scan_btn_scanning);
        } else if (prefs.autoRefresh() && !accessPoints.isEmpty()) {
            b.countdownText.setText(getString(R.string.scan_next_in, repo.countdown));
        } else {
            b.countdownText.setText("");
        }

        // The scan may have found networks that were then filtered out because they
        // cannot run PixieDust. Say that plainly instead of showing the "plug an
        // adapter" empty state for a scan that actually worked.
        int found = repo.lastScan == null ? 0 : repo.lastScan.aps.size();
        boolean allFiltered = found > 0 && accessPoints.isEmpty() && !prefs.showAllNetworks();
        if (allFiltered) {
            b.emptyTitle.setText(R.string.scan_none_candidates_title);
            b.emptyBody.setText(getString(R.string.scan_none_candidates_body, found));
        } else {
            b.emptyTitle.setText(R.string.scan_empty_title);
            b.emptyBody.setText(R.string.scan_empty_body);
        }

        b.progress.setVisibility(repo.scanning ? View.VISIBLE : View.GONE);
        b.btnScan.setEnabled(!repo.scanning && !repo.attacking && !repo.capturing);
        b.btnScan.setText(repo.scanning ? R.string.scan_btn_scanning : R.string.scan_btn_scan);

        PixieError error = repo.error;
        boolean showError = error != null && !repo.scanning;
        b.emptyState.setVisibility(
                !repo.scanning && !showError && accessPoints.isEmpty() ? View.VISIBLE : View.GONE);
        b.errorCard.setVisibility(showError ? View.VISIBLE : View.GONE);
        if (showError) {
            b.errorMessage.setText(error.kind == PixieError.Kind.NO_BEACONS
                    ? getString(R.string.err_no_beacons, error.rxFrames)
                    : getString(error.messageRes()));
            String details = error.technicalDetail();
            b.errorDetails.setText(details);
            b.errorDetails.setVisibility(details.isEmpty() ? View.GONE : View.VISIBLE);
        }

        adapter.submit(accessPoints);
        applyKeepScreenOn();
    }

    private void applyKeepScreenOn() {
        if (prefs.keepScreenOn()) {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        } else {
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
    }
}
