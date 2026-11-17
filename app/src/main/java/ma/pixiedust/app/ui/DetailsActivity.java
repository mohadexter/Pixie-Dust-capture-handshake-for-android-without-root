package ma.pixiedust.app.ui;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;

import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.databinding.ActivityDetailsBinding;

/** One access point: the exact plan and the single PixieDust consent. */
public class DetailsActivity extends AppCompatActivity {

    private ActivityDetailsBinding b;
    private Prefs prefs;
    private Data.AccessPoint ap;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityDetailsBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        prefs = PixieApp.from(this).prefs();

        ap = Ui.getAp(getIntent());
        if (ap == null) {
            finish();
            return;
        }

        b.btnBack.setOnClickListener(v -> finish());
        bindHero();
        bindOptions();
        bindBlockedState();

        b.btnStart.setOnClickListener(v -> confirmConsent());
    }

    private void bindHero() {
        b.ssidText.setText(ap.displayName(getString(R.string.scan_hidden)));
        b.bssidText.setText(ap.bssid);
        b.chipChannel.setText(getString(R.string.scan_ch, ap.channel));
        b.chipBand.setText(Ui.band(this, ap.channel));
        b.chipSecurity.setText(ap.encryption.isEmpty() ? "\u2014" : ap.encryption);
        b.chipWps.setText(ap.wps
                ? getString(R.string.details_wps_on, ap.wpsVersion)
                : "WPS");
        b.chipWps.setVisibility(ap.wps ? View.VISIBLE : View.GONE);
        b.chipClients.setText(ap.clients > 0
                ? getString(R.string.details_clients, ap.clients)
                : getString(R.string.details_clients_none));
        b.lockedCard.setVisibility(ap.locked ? View.VISIBLE : View.GONE);
    }

    private void bindOptions() {
        b.switchDeep.setChecked(prefs.deepMode());
        b.switchVerify.setChecked(prefs.liveVerify());
    }

    private void bindBlockedState() {
        boolean attackable = ap.canAttack();
        b.btnStart.setEnabled(attackable);
        b.btnStart.setAlpha(attackable ? 1f : 0.5f);
        b.blockedCard.setVisibility(attackable ? View.GONE : View.VISIBLE);
        if (!attackable) {
            b.blockedBody.setText(blockedReasonRes());
        }
    }

    private int blockedReasonRes() {
        if (!ap.wps) {
            return R.string.details_blocked_no_wps;
        }
        if (ap.isHidden()) {
            return R.string.details_blocked_hidden;
        }
        return R.string.details_blocked_channel;
    }

    private void confirmConsent() {
        boolean deep = b.switchDeep.isChecked();
        boolean verify = b.switchVerify.isChecked();
        prefs.setDeepMode(deep);
        prefs.setLiveVerify(verify);

        String message = getString(R.string.details_consent_body,
                ap.displayName(getString(R.string.scan_hidden)));
        if (ap.locked) {
            message = message + "\n\n" + getString(R.string.details_consent_locked);
        }

        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.details_consent_title)
                .setMessage(message)
                .setNegativeButton(R.string.generic_cancel, null)
                .setPositiveButton(R.string.details_consent_start, (dialog, which) -> startRun(deep, verify))
                .show();
    }

    private void startRun(boolean deep, boolean verify) {
        Intent intent = new Intent(this, AttackActivity.class);
        Ui.putAp(intent, ap);
        intent.putExtra("deep", deep);
        intent.putExtra("verify", verify);
        startActivity(intent);
        finish();
    }
}
