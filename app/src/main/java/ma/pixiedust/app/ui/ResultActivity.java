package ma.pixiedust.app.ui;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.core.widget.TextViewCompat;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.PixieError;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.databinding.ActivityResultBinding;
import ma.pixiedust.app.service.AttackService;

/** PIN and PSK on one screen: what the run recovered, and what it could not. */
public class ResultActivity extends AppCompatActivity implements Repo.Listener {

    private ActivityResultBinding b;
    private Repo repo;
    private Data.AccessPoint ap;
    private boolean pskRevealed;
    private boolean pinRevealed;
    private boolean vibrated;
    private boolean successDialogShown;
    private String summaryKey = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityResultBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        PixieApp app = PixieApp.from(this);
        repo = app.repo();
        ap = Ui.getAp(getIntent());
        if (ap == null) {
            ap = repo.target;
        }

        b.btnBack.setOnClickListener(v -> finish());
        b.btnRescan.setOnClickListener(v -> rescan());
        b.btnCopyPin.setOnClickListener(v -> Ui.copy(this, currentPin()));
        b.btnCopyPsk.setOnClickListener(v -> {
            Data.Verify verify = repo.verify;
            if (verify != null) {
                Ui.copy(this, verify.psk);
            }
        });
        b.btnVerify.setOnClickListener(v -> verifyNow());
        render();
    }

    @Override
    protected void onResume() {
        super.onResume();
        repo.addListener(this);
        repo.setForeground(true);
        render();
    }

    @Override
    protected void onPause() {
        repo.setForeground(false);
        repo.removeListener(this);
        super.onPause();
    }

    @Override
    public void onState() {
        render();
    }

    private String currentPin() {
        Data.Crack crack = repo.crack;
        if (crack != null && crack.pin != null && !crack.pin.isEmpty()) {
            return crack.pin;
        }
        Data.Verify verify = repo.verify;
        if (verify != null && verify.pin != null) {
            return verify.pin;
        }
        return "";
    }

    private void verifyNow() {
        String pin = currentPin();
        if (pin.isEmpty() || ap == null || ap.channel < 1 || ap.channel > 14) {
            return;
        }
        b.btnVerify.setEnabled(false);
        AttackService.start(this);
        repo.verifyPin(ap, pin);
        render();
    }

    private void rescan() {
        Intent intent = new Intent(this, ScanActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("rescan", true);
        startActivity(intent);
        finish();
    }

    /**
     * A small success frame shown once, when a value really was recovered. The PIN
     * and password sit in a heavier monospace line so they can be read at a glance.
     */
    private void showSuccessDialog(String pin, String psk) {
        if (isFinishing() || isDestroyed()) {
            return;
        }
        View content = getLayoutInflater().inflate(R.layout.dialog_success, null);
        TextView title = content.findViewById(R.id.dlgTitle);
        TextView body = content.findViewById(R.id.dlgBody);
        TextView value = content.findViewById(R.id.dlgValue);

        title.setText(R.string.success_title);
        body.setText(psk != null ? R.string.success_psk : R.string.success_pin);

        StringBuilder text = new StringBuilder();
        if (psk != null) {
            text.append(getString(R.string.result_psk_label)).append("  ").append(psk);
        }
        if (pin != null && !pin.isEmpty()) {
            if (text.length() > 0) {
                text.append('\n');
            }
            text.append(getString(R.string.result_pin_label)).append("  ")
                    .append(Ui.pinGroups(pin));
        }
        value.setText(text);

        new MaterialAlertDialogBuilder(this)
                .setView(content)
                .setPositiveButton(R.string.success_dialog_copy,
                        (d, w) -> Ui.copy(this, text.toString(), R.string.result_copied))
                .setNegativeButton(R.string.generic_close, null)
                .show();
    }

    private void render() {
        if (b == null) {
            return;
        }
        String pin = currentPin();
        boolean hasPin = !pin.isEmpty();

        Data.Verify verify = repo.verify;
        String psk = verify != null && verify.hasPsk() ? verify.psk : null;
        boolean hasPsk = psk != null;

        // PIN card
        b.pinCard.setVisibility(hasPin ? View.VISIBLE : View.GONE);
        if (hasPin) {
            String compactPin = Ui.pinGroups(pin);
            if (!pinRevealed) {
                pinRevealed = true;
                Ui.revealDecoding(b.pinText, compactPin);
                Ui.enter(b.pinCard);
            } else {
                b.pinText.setText(compactPin);
            }
        }

        // PSK card: never empty, always labelled with the real state.
        if (hasPsk) {
            b.pskText.setVisibility(View.VISIBLE);
            if (!pskRevealed) {
                pskRevealed = true;
                Ui.revealDecoding(b.pskText, psk);
                Ui.enter(b.pskCard);
            } else {
                b.pskText.setText(psk);
            }
            b.pskMessage.setVisibility(View.GONE);
            b.btnCopyPsk.setVisibility(View.VISIBLE);
        } else {
            b.pskText.setVisibility(View.GONE);
            b.pskMessage.setVisibility(View.VISIBLE);
            b.btnCopyPsk.setVisibility(View.GONE);
            boolean pinAccepted = hasPin && verify != null && verify.attempted;
            b.pskMessage.setText(pinAccepted
                    ? R.string.result_psk_pending
                    : R.string.result_psk_none);
        }

        // Status + the success banner, announced only for a value that exists.
        boolean recovered = hasPsk || hasPin;
        if (recovered && !vibrated) {
            vibrated = true;
            Ui.vibrateSuccess(this);
            b.successCard.setVisibility(View.VISIBLE);
            b.successText.setText(hasPsk ? R.string.success_psk : R.string.success_pin);
            b.successSub.setText(R.string.success_hint);
            Ui.enter(b.successCard);
        } else if (!recovered) {
            b.successCard.setVisibility(View.GONE);
        }

        if (recovered && !successDialogShown) {
            successDialogShown = true;
            showSuccessDialog(pin, psk);
        }

        if (hasPsk) {
            styleStatus(R.string.result_status_pin_psk, R.drawable.bg_pill_green, R.color.green);
        } else if (hasPin) {
            styleStatus(R.string.result_status_pin_only, R.drawable.bg_pill_amber, R.color.amber);
        } else {
            styleStatus(R.string.result_status_failed, R.drawable.bg_pill_red, R.color.red);
        }

        // Verify button: only useful with a PIN and no PSK.
        boolean canVerify = hasPin && !hasPsk
                && ap != null && ap.channel >= 1 && ap.channel <= 14;
        b.btnVerify.setVisibility(canVerify ? View.VISIBLE : View.GONE);
        b.btnVerify.setEnabled(canVerify && !repo.attacking);

        // Error
        PixieError error = repo.error;
        boolean showError = error != null;
        b.errorCard.setVisibility(showError ? View.VISIBLE : View.GONE);
        if (showError) {
            b.errorMessage.setText(error.kind == PixieError.Kind.NO_BEACONS
                    ? getString(R.string.err_no_beacons, error.rxFrames)
                    : getString(error.messageRes()));
            String details = error.technicalDetail();
            b.errorDetails.setText(details);
            b.errorDetails.setVisibility(details.isEmpty() ? View.GONE : View.VISIBLE);
        }

        // Hero: network identity, so the values below always have a context.
        String ssid = ap == null ? "" : ap.displayName(getString(R.string.scan_hidden));
        b.heroSsid.setText(Ui.orDash(ssid));
        b.statusText.setText(Ui.orDash(ssid));
        String vendor = ap == null || ap.vendor.isEmpty()
                ? getString(R.string.result_vendor_unknown)
                : ap.vendor;
        String model = ap == null ? "" : ap.model;
        String device = model.isEmpty()
                ? vendor
                : getString(R.string.device_vendor_model, vendor, model);
        b.heroMeta.setText(Ui.orDash(ap == null ? "" : ap.bssid) + " \u00B7 " + device);

        renderSummary(psk, pin);
    }

    /**
     * One table with the four facts the user came for: network, MAC, password, PIN.
     * Rebuilt only when a value changes, so the reveal animation runs once.
     */
    private void renderSummary(String psk, String pin) {
        String ssid = ap == null ? "" : ap.displayName(getString(R.string.scan_hidden));
        String mac = ap == null ? "" : ap.bssid;
        int clients = ap == null ? 0 : ap.clients;
        String model = ap == null || ap.model.isEmpty()
                ? getString(R.string.result_model_unknown) : ap.model;
        String key = ssid + "|" + mac + "|" + clients + "|" + model + "|" + psk + "|" + pin;
        if (key.equals(summaryKey)) {
            return;
        }
        summaryKey = key;

        b.summaryContainer.removeAllViews();
        addSummaryRow(R.string.result_table_ssid, ssid, false);
        addSummaryRow(R.string.result_table_bssid, mac, true);
        addSummaryRow(R.string.result_table_vendor,
                ap == null || ap.vendor.isEmpty() ? getString(R.string.result_vendor_unknown) : ap.vendor,
                false);
        addSummaryRow(R.string.result_table_model, model, false);
        addSummaryRow(R.string.result_table_psk, psk, true);
        addSummaryRow(R.string.result_table_pin, pin.isEmpty() ? "" : Ui.pinGroups(pin), true);
        if (clients > 0) {
            addSummaryRow(R.string.result_table_clients, String.valueOf(clients), false);
        }
        Ui.enter(b.summaryContainer);
    }

    private void addSummaryRow(int labelRes, String value, boolean mono) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        int pad = (int) Ui.dp(this, 6f);
        row.setPadding(0, pad, 0, pad);

        TextView label = new TextView(this);
        label.setText(labelRes);
        TextViewCompat.setTextAppearance(label, R.style.TextAppearance_PixieDust_Caption);
        label.setLayoutParams(new LinearLayout.LayoutParams(
                (int) Ui.dp(this, 96f), LinearLayout.LayoutParams.WRAP_CONTENT));
        row.addView(label);

        TextView content = new TextView(this);
        content.setText(Ui.orDash(value));
        TextViewCompat.setTextAppearance(content,
                mono ? R.style.TextAppearance_PixieDust_Mono : R.style.TextAppearance_PixieDust_Body);
        content.setTextIsSelectable(true);
        content.setLayoutParams(new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        row.addView(content);

        b.summaryContainer.addView(row);
    }

    private void styleStatus(int textRes, int backgroundRes, int colorRes) {
        b.statusPill.setText(textRes);
        b.statusPill.setBackgroundResource(backgroundRes);
        b.statusPill.setTextColor(ContextCompat.getColor(this, colorRes));
        b.statusText.setText(ap == null
                ? ""
                : ap.displayName(getString(R.string.scan_hidden)));
    }
}
