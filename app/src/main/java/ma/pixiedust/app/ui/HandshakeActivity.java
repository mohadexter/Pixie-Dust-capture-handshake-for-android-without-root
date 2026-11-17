package ma.pixiedust.app.ui;

import android.animation.ValueAnimator;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import java.util.List;
import java.util.Locale;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.databinding.ActivityHandshakeBinding;

/**
 * One handshake capture: monitor RX stays on, a bounded deauth burst provokes a
 * re-handshake, and the result is saved to the handshake folder chosen in Settings.
 * A single button starts and stops the capture; every stage is spelled out for a
 * beginner, and success is only announced when a file really exists.
 */
public class HandshakeActivity extends AppCompatActivity implements Repo.Listener {

    private static final int CAPTURE_SECONDS = 120;

    private ActivityHandshakeBinding b;
    private Repo repo;
    private Data.AccessPoint ap;
    private ValueAnimator pulse;
    private boolean vibrated;
    private boolean successDialogShown;

    public static void start(android.app.Activity from, Data.AccessPoint ap) {
        Intent intent = new Intent(from, HandshakeActivity.class);
        Ui.putAp(intent, ap);
        from.startActivity(intent);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityHandshakeBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        repo = PixieApp.from(this).repo();
        ap = Ui.getAp(getIntent());
        if (ap == null) {
            finish();
            return;
        }

        b.targetText.setText(getString(R.string.handshake_target,
                ap.displayName(getString(R.string.scan_hidden)), ap.bssid));
        b.stepper.setStepCount(5);

        b.btnBack.setOnClickListener(v -> leave());
        b.btnStart.setOnClickListener(v -> primaryAction());

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                leave();
            }
        });

        render();
        confirmAndStart();
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

    @Override
    public void onState() {
        render();
    }

    // ------------------------------------------------------------------ actions

    /** The one main button: start when idle, stop while the capture runs. */
    private void primaryAction() {
        if (repo.capturing) {
            repo.cancelCapture();
            return;
        }
        confirmAndStart();
    }

    private void confirmAndStart() {
        if (repo.capturing) {
            return;
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.handshake_consent_title)
                .setMessage(getString(R.string.handshake_consent_body,
                        ap.displayName(getString(R.string.scan_hidden))))
                .setNegativeButton(R.string.generic_cancel, (d, w) -> render())
                .setPositiveButton(R.string.handshake_consent_start, (d, w) -> begin())
                .show();
    }

    private void begin() {
        vibrated = false;
        successDialogShown = false;
        repo.note(getString(R.string.hs_log_1, ap.channel));
        repo.note(getString(R.string.hs_log_2));
        repo.note(getString(R.string.hs_log_3));
        repo.note(getString(R.string.hs_log_4));
        repo.note(getString(R.string.hs_log_5));
        repo.captureHandshake(ap, CAPTURE_SECONDS, true);
        render();
    }

    private void leave() {
        if (repo.capturing) {
            new MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.attack_cancel_confirm)
                    .setMessage(R.string.handshake_stop_body)
                    .setNegativeButton(R.string.attack_keep_open, null)
                    .setPositiveButton(R.string.handshake_stop, (d, w) -> {
                        repo.cancelCapture();
                        finish();
                    })
                    .show();
            return;
        }
        finish();
    }

    // ------------------------------------------------------------------- render

    private void render() {
        if (b == null) {
            return;
        }
        Data.Handshake handshake = repo.handshake;
        boolean running = repo.capturing;
        boolean finished = !running && handshake != null;
        boolean hasFile = handshake != null && handshake.hasFile() && handshake.complete;

        int step = step();
        b.stepper.setStep(step, finished && !hasFile, finished && hasFile);
        b.stageText.setText(stageLabel(step));
        b.detailText.setText(detail(step));
        b.progress.setVisibility(running ? View.VISIBLE : View.GONE);

        // One button does both jobs; its label always says what a tap will do.
        b.btnStart.setText(running ? R.string.handshake_stop : R.string.handshake_start);
        b.btnStart.setIconResource(running ? R.drawable.ic_close : R.drawable.ic_play);
        b.btnStart.setEnabled(true);
        updatePulse(running);

        b.successCard.setVisibility(handshake == null ? View.GONE : View.VISIBLE);
        if (handshake != null) {
            if (hasFile) {
                b.successCard.setCardBackgroundColor(getColor(R.color.green_soft));
                b.successIcon.setImageResource(R.drawable.ic_check);
                b.successIcon.setImageTintList(ColorStateList.valueOf(getColor(R.color.green)));
                b.successText.setText(R.string.handshake_valid_title);
                b.successText.setTextColor(getColor(R.color.green));
                b.successSub.setTextColor(getColor(R.color.green));
                b.successSub.setText(getString(R.string.handshake_valid_sub,
                        handshake.displayPath()));
            } else if (!handshake.error.isEmpty()) {
                b.successCard.setCardBackgroundColor(getColor(R.color.red_soft));
                b.successIcon.setImageResource(R.drawable.ic_warning);
                b.successIcon.setImageTintList(ColorStateList.valueOf(getColor(R.color.red)));
                b.successText.setText(R.string.handshake_failed_title);
                b.successText.setTextColor(getColor(R.color.red));
                b.successSub.setTextColor(getColor(R.color.red));
                b.successSub.setText(handshake.error);
            } else {
                b.successCard.setCardBackgroundColor(getColor(R.color.amber_soft));
                b.successIcon.setImageResource(R.drawable.ic_warning);
                b.successIcon.setImageTintList(ColorStateList.valueOf(getColor(R.color.amber)));
                b.successText.setText(R.string.handshake_no_valid_title);
                b.successText.setTextColor(getColor(R.color.amber));
                b.successSub.setTextColor(getColor(R.color.amber));
                b.successSub.setText(getString(R.string.handshake_no_valid_sub, reason(handshake)));
            }

            StringBuilder stats = new StringBuilder(getString(R.string.handshake_stats,
                    handshake.frames,
                    handshake.eapolFrames,
                    handshake.clients,
                    String.format(Locale.US, "%.1fs", handshake.elapsedS)));
            if (handshake.deauthSent > 0) {
                stats.append("  ·  ").append(getString(R.string.handshake_deauth_stats,
                        handshake.deauthSent, handshake.deauthAcked, handshake.deauthBursts));
            }
            if (handshake.complete) {
                stats.append('\n').append(getString(R.string.handshake_pair_line,
                        Ui.orDash(handshake.pair),
                        handshake.validPairs,
                        Ui.orDash(handshake.clientMac)));
            }
            b.statsText.setText(stats);
            b.statsText.setVisibility(View.VISIBLE);
        } else {
            b.statsText.setVisibility(View.GONE);
        }

        b.logText.setText(joinLogs(repo.logs));
        b.logScroll.post(() -> b.logScroll.fullScroll(View.FOCUS_DOWN));

        if (hasFile && !vibrated) {
            vibrated = true;
            Ui.vibrateSuccess(this);
            Ui.enter(b.successCard);
        }
        if (hasFile && !successDialogShown) {
            successDialogShown = true;
            showSuccessDialog(handshake);
        }
    }

    /**
     * Small frame over the screen: the success, the file path in a heavier
     * monospace line, and the actions that matter (open the file, copy the path).
     */
    private void showSuccessDialog(Data.Handshake handshake) {
        if (isFinishing()) {
            return;
        }
        View content = getLayoutInflater().inflate(R.layout.dialog_success, null);
        TextView title = content.findViewById(R.id.dlgTitle);
        TextView body = content.findViewById(R.id.dlgBody);
        TextView value = content.findViewById(R.id.dlgValue);
        title.setText(R.string.hs_dialog_title);
        body.setText(R.string.hs_dialog_body);
        value.setText(handshake.displayPath());

        new MaterialAlertDialogBuilder(this)
                .setView(content)
                .setPositiveButton(R.string.hs_dialog_open, (d, w) -> {
                    String path = handshake.displayPath();
                    if (!Ui.openDocument(this, handshake.publicUri, path,
                            "application/vnd.tcpdump.pcap")) {
                        Ui.copy(this, path, R.string.handshake_path_copied);
                        Ui.toast(this, R.string.hs_dialog_open_failed);
                    }
                })
                .setNeutralButton(R.string.handshake_copy_path,
                        (d, w) -> Ui.copy(this, handshake.displayPath(),
                                R.string.handshake_path_copied))
                .setNegativeButton(R.string.generic_close, null)
                .show();
    }

    /** Last honest note from the engine, without the deauth bookkeeping lines. */
    private String reason(Data.Handshake handshake) {
        if (handshake.notes != null) {
            for (int i = handshake.notes.size() - 1; i >= 0; i--) {
                String note = handshake.notes.get(i);
                if (note != null && !note.isEmpty()
                        && !note.startsWith("deauth burst")
                        && !note.startsWith("cancelled by")) {
                    return note;
                }
            }
        }
        return getString(R.string.handshake_no_valid_reason);
    }

    private int step() {
        if (!repo.capturing) {
            return repo.handshake != null ? 4 : 0;
        }
        if (!repo.isSessionOpen()) {
            return 0;
        }
        if (sawDeauth()) {
            return repo.handshake == null ? 2 : 3;
        }
        return 1;
    }

    private boolean sawDeauth() {
        for (String line : repo.logs) {
            if (line.contains("deauth burst") || line.contains("deauth")) {
                return true;
            }
        }
        return false;
    }

    private int stageLabel(int step) {
        switch (step) {
            case 0:
                return R.string.hs_stage_usb;
            case 1:
                return R.string.hs_stage_monitor;
            case 2:
                return R.string.hs_stage_deauth;
            case 3:
                return R.string.hs_stage_extract;
            default:
                return R.string.hs_stage_save;
        }
    }

    private CharSequence detail(int step) {
        switch (step) {
            case 0:
                return getString(R.string.hs_detail_usb);
            case 1:
                return getString(R.string.hs_detail_monitor, ap.channel);
            case 2:
                return getString(R.string.hs_detail_deauth);
            case 3:
                return getString(R.string.hs_detail_extract);
            default:
                return repo.capturing
                        ? getString(R.string.hs_detail_saving)
                        : getString(R.string.hs_detail_done);
        }
    }

    private void updatePulse(boolean running) {
        if (running && pulse == null) {
            pulse = ValueAnimator.ofFloat(0.35f, 1f);
            pulse.setDuration(850L);
            pulse.setRepeatMode(ValueAnimator.REVERSE);
            pulse.setRepeatCount(ValueAnimator.INFINITE);
            pulse.addUpdateListener(animation -> {
                float value = (float) animation.getAnimatedValue();
                b.pulseIcon.setAlpha(value);
                float scale = 0.85f + value * 0.25f;
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
        StringBuilder sb = new StringBuilder();
        for (String line : lines) {
            sb.append(line).append('\n');
        }
        return sb.toString();
    }
}
