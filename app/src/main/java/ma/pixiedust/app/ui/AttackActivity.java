package ma.pixiedust.app.ui;

import android.animation.ValueAnimator;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.databinding.ActivityAttackBinding;
import ma.pixiedust.app.service.AttackService;

/** Drives exactly one Pixie Dust attempt and shows its live log. */
public class AttackActivity extends AppCompatActivity implements Repo.Listener {

    private ActivityAttackBinding b;
    private Repo repo;
    private Data.AccessPoint ap;
    private int lastStep = 0;
    private String lastLog = "";
    private boolean navigated;
    private boolean vibrated;
    private ValueAnimator pulse;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityAttackBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        PixieApp app = PixieApp.from(this);
        repo = app.repo();
        Prefs prefs = app.prefs();

        ap = Ui.getAp(getIntent());
        if (ap == null) {
            finish();
            return;
        }

        b.targetText.setText(ap.displayName(getString(R.string.scan_hidden)));
        b.btnStop.setOnClickListener(v -> confirmStop());
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                confirmStop();
            }
        });

        boolean deep = getIntent().getBooleanExtra("deep", prefs.deepMode());
        boolean verify = getIntent().getBooleanExtra("verify", prefs.liveVerify());

        // A configuration change must never start a second WPS attempt.
        boolean alreadyRunning = repo.attacking
                && repo.target != null
                && ap.bssid.equalsIgnoreCase(repo.target.bssid);
        if (!alreadyRunning) {
            repo.startAttack(ap, deep, verify);
        }
        AttackService.start(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
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
    protected void onDestroy() {
        getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        stopPulse();
        super.onDestroy();
    }

    private void confirmStop() {
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.attack_cancel_confirm)
                .setMessage(R.string.attack_cancel_body)
                .setNegativeButton(R.string.generic_cancel, null)
                .setPositiveButton(R.string.attack_cancel, (dialog, which) -> {
                    repo.cancelAttack();
                    AttackService.stop(this);
                    finish();
                })
                .show();
    }

    @Override
    public void onState() {
        render();
    }

    private void render() {
        if (b == null) {
            return;
        }
        Data.Stage stage = repo.stage;
        boolean failed = stage == Data.Stage.FAILED;
        boolean done = stage == Data.Stage.DONE;
        if (stage != Data.Stage.FAILED) {
            lastStep = stepIndex(stage);
        }
        b.stepper.setStep(lastStep, failed, done);
        b.stageText.setText(stepLabel(stage));
        b.detailText.setText(detailFor(stage));
        b.factsText.setText(facts());
        b.progress.setVisibility(repo.attacking ? View.VISIBLE : View.GONE);
        b.btnStop.setEnabled(repo.attacking);
        updatePulse(repo.attacking);

        // Success is only announced when the engine really produced a value.
        Data.Crack crack = repo.crack;
        Data.Verify verify = repo.verify;
        boolean recovered = done && ((crack != null && crack.pin != null && !crack.pin.isEmpty())
                || (verify != null && verify.hasPsk()));
        if (recovered && !vibrated) {
            vibrated = true;
            Ui.vibrateSuccess(this);
            b.successCard.setVisibility(View.VISIBLE);
            b.successText.setText(verify != null && verify.hasPsk()
                    ? R.string.success_psk : R.string.success_pin);
            b.successSub.setText(R.string.success_hint);
            Ui.enter(b.successCard);
        }

        String logs = joinLogs(repo.logs);
        if (!logs.equals(lastLog)) {
            lastLog = logs;
            b.logText.setText(logs);
            b.logScroll.post(() -> b.logScroll.fullScroll(View.FOCUS_DOWN));
        }

        if (!navigated && !repo.attacking && (done || failed)) {
            navigated = true;
            AttackService.stop(this);
            Intent intent = new Intent(this, ResultActivity.class);
            Ui.putAp(intent, ap);
            startActivity(intent);
            finish();
        }
    }

    private int stepIndex(Data.Stage stage) {
        switch (stage) {
            case USB:
                return 0;
            case CAPTURE:
                return 1;
            case OFFLINE:
                return 2;
            case VERIFY:
                return 3;
            case PASSWORD:
                return 4;
            case DONE:
            case FAILED:
            default:
                return 5;
        }
    }

    private int stepLabel(Data.Stage stage) {        switch (stage) {
            case USB:
                return R.string.attack_step_usb;
            case CAPTURE:
                return R.string.attack_step_capture;
            case OFFLINE:
                return R.string.attack_step_offline;
            case VERIFY:
                return R.string.attack_step_verify;
            case PASSWORD:
                return R.string.attack_step_password;
            case DONE:
                return R.string.attack_step_done;
            case FAILED:
            default:
                return R.string.attack_step_failed;
        }
    }

    /** Plain-language explanation of the step that is running right now. */
    private CharSequence detailFor(Data.Stage stage) {
        switch (stage) {
            case USB:
                return getString(R.string.attack_detail_usb);
            case CAPTURE:
                return getString(R.string.attack_detail_capture, ap == null ? 0 : ap.channel);
            case OFFLINE:
                return getString(R.string.attack_detail_offline);
            case VERIFY:
                return getString(R.string.attack_detail_verify);
            case PASSWORD:
                return getString(R.string.attack_detail_password);
            case DONE:
                return getString(R.string.attack_detail_done);
            case FAILED:
            default:
                return getString(R.string.attack_detail_failed);
        }
    }

    /** Facts already proven by the engine, joined into one monospace line. */
    private String facts() {
        List<String> parts = new ArrayList<>();
        if (repo.capture != null) {
            parts.add(getString(R.string.attack_facts_capture));
        }
        if (repo.crack != null && repo.crack.pin != null && !repo.crack.pin.isEmpty()) {
            String time = String.format(Locale.US, "%.1fs", Math.max(0f, repo.crack.seconds));
            parts.add(getString(R.string.attack_facts_crack, time));
        }
        Data.Verify verify = repo.verify;
        if (verify != null && verify.hasPsk()) {
            parts.add(getString(R.string.attack_facts_verify));
        }
        if (parts.isEmpty()) {
            return getString(R.string.attack_facts_none);
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < parts.size(); i++) {
            if (i > 0) {
                sb.append("  ·  ");
            }
            sb.append(parts.get(i));
        }
        return sb.toString();
    }

    /** Pulsing spark while the engine is busy; stops dead when it is not. */
    private void updatePulse(boolean running) {
        if (running && pulse == null) {
            pulse = ValueAnimator.ofFloat(0.35f, 1f);
            pulse.setDuration(900L);
            pulse.setRepeatMode(ValueAnimator.REVERSE);
            pulse.setRepeatCount(ValueAnimator.INFINITE);
            pulse.addUpdateListener(animation -> {
                float value = (float) animation.getAnimatedValue();
                b.pulseIcon.setAlpha(value);
                float scale = 0.82f + value * 0.32f;
                b.pulseIcon.setScaleX(scale);
                b.pulseIcon.setScaleY(scale);
            });
            pulse.start();
        } else if (!running) {
            stopPulse();
        }
    }

    private void stopPulse() {
        if (pulse != null) {
            pulse.cancel();
            pulse = null;
        }
        if (b != null) {
            b.pulseIcon.setAlpha(1f);
            b.pulseIcon.setScaleX(1f);
            b.pulseIcon.setScaleY(1f);
        }
    }

    private static String joinLogs(List<String> lines) {
        if (lines == null || lines.isEmpty()) {
            return "";
        }
        int from = Math.max(0, lines.size() - 250);
        StringBuilder sb = new StringBuilder();
        for (int i = from; i < lines.size(); i++) {
            if (i > from) {
                sb.append('\n');
            }
            sb.append(lines.get(i));
        }
        return sb.toString();
    }
}
