package ma.pixiedust.app.ui;

import android.graphics.Typeface;
import android.hardware.usb.UsbDevice;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.core.widget.TextViewCompat;

import java.util.List;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Bridge;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.databinding.ActivityDriversBinding;
import ma.pixiedust.app.usb.Adapters;
import ma.pixiedust.app.usb.UsbOtg;

/** Adapter inspection: permission, a passive driver test, and the supported list. */
public class DriversActivity extends AppCompatActivity {

    private ActivityDriversBinding b;
    private UsbOtg usb;
    private Repo repo;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityDriversBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        PixieApp app = PixieApp.from(this);
        usb = app.usb();
        repo = app.repo();

        b.btnBack.setOnClickListener(v -> finish());
        b.btnPermission.setOnClickListener(v -> {
            UsbDevice device = usb.findAttached();
            if (device == null) {
                Ui.toast(this, R.string.err_no_device);
                return;
            }
            usb.requestPermission(device);
            // The system dialog answers through a broadcast; check a few times after it.
            handler.postDelayed(this::render, 800L);
            handler.postDelayed(this::render, 2_500L);
        });
        b.btnTest.setOnClickListener(v -> runDriverTest());

        fillSupportedList();
        render();
        repo.selfTest(this::showSelfTest);
    }

    private void showSelfTest(Bridge.SelfTest result) {
        if (result == null) {
            return;
        }
        if (result.ok) {
            String abi = Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "";
            b.engineStatus.setText(getString(R.string.drivers_engine_ok, result.version, abi));
            b.engineStatus.setTextColor(ContextCompat.getColor(this, R.color.green));
            b.engineDetail.setVisibility(View.GONE);
            return;
        }
        b.engineStatus.setText(R.string.drivers_engine_fail);
        b.engineStatus.setTextColor(ContextCompat.getColor(this, R.color.red));
        b.engineDetail.setText(result.error);
        b.engineDetail.setVisibility(result.error == null || result.error.isEmpty()
                ? View.GONE : View.VISIBLE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        render();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private void render() {
        Data.UsbAdapter adapter = repo.currentAdapter();
        if (adapter == null) {
            b.adapterCard.setVisibility(View.GONE);
            b.noneCard.setVisibility(View.VISIBLE);
            return;
        }
        b.adapterCard.setVisibility(View.VISIBLE);
        b.noneCard.setVisibility(View.GONE);

        String name = adapter.productName == null || adapter.productName.isEmpty()
                ? adapter.chipset : adapter.productName;
        b.adapterName.setText(name);
        b.adapterVidPid.setText(getString(R.string.drivers_vidpid, adapter.vidPid()));
        b.adapterChipset.setText(adapter.chipset + "  \u00b7  " + adapter.driverModule);

        if (adapter.supported) {
            b.adapterStatus.setText(R.string.drivers_supported);
            b.adapterStatus.setBackgroundResource(R.drawable.bg_pill_green);
            b.adapterStatus.setTextColor(ContextCompat.getColor(this, R.color.green));
        } else {
            b.adapterStatus.setText(R.string.drivers_unknown);
            b.adapterStatus.setBackgroundResource(R.drawable.bg_pill_amber);
            b.adapterStatus.setTextColor(ContextCompat.getColor(this, R.color.amber));
        }

        b.btnPermission.setVisibility(adapter.hasPermission ? View.GONE : View.VISIBLE);
        b.btnTest.setEnabled(adapter.supported && adapter.hasPermission);
        b.btnTest.setAlpha(adapter.supported && adapter.hasPermission ? 1f : 0.5f);
    }

    private void runDriverTest() {
        b.btnTest.setEnabled(false);
        b.btnTest.setText(R.string.drivers_testing);
        b.stepsCard.setVisibility(View.VISIBLE);
        b.stepsContainer.removeAllViews();
        repo.testDriver(steps -> {
            b.btnTest.setText(R.string.drivers_test);
            b.btnTest.setEnabled(true);
            showSteps(steps);
            render();
        });
    }

    private void showSteps(List<Data.DriverStep> steps) {
        b.stepsContainer.removeAllViews();
        if (steps == null) {
            return;
        }
        for (Data.DriverStep step : steps) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.TOP);
            int pad = (int) Ui.dp(this, 6);
            row.setPadding(0, pad, 0, pad);

            TextView dot = new TextView(this);
            dot.setText(step.ok ? "\u25CF" : "\u25CF");
            dot.setTextSize(11f);
            dot.setTextColor(ContextCompat.getColor(this, step.ok ? R.color.green : R.color.red));
            dot.setPadding(0, (int) Ui.dp(this, 2), (int) Ui.dp(this, 8), 0);
            row.addView(dot);

            LinearLayout column = new LinearLayout(this);
            column.setOrientation(LinearLayout.VERTICAL);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                    0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
            column.setLayoutParams(params);

            TextView name = new TextView(this);
            name.setText(step.name);
            name.setTextSize(14f);
            name.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
            name.setTextColor(ContextCompat.getColor(this, R.color.ink));
            column.addView(name);

            TextView detail = new TextView(this);
            detail.setText(step.detail);
            TextViewCompat.setTextAppearance(detail, R.style.TextAppearance_PixieDust_Caption);
            column.addView(detail);

            row.addView(column);
            b.stepsContainer.addView(row);
        }
    }

    private void fillSupportedList() {
        b.supportedContainer.removeAllViews();
        int pad = (int) Ui.dp(this, 7);
        for (Adapters.Info info : Adapters.all()) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.VERTICAL);
            row.setPadding(0, pad, 0, pad);

            TextView title = new TextView(this);
            title.setText(info.name);
            title.setTextSize(14f);
            title.setTextColor(ContextCompat.getColor(this, R.color.ink));
            row.addView(title);

            TextView meta = new TextView(this);
            meta.setText("0x" + info.vidPid() + "  \u00b7  " + info.chipset + "  \u00b7  " + info.bands);
            TextViewCompat.setTextAppearance(meta, R.style.TextAppearance_PixieDust_Caption);
            row.addView(meta);

            b.supportedContainer.addView(row);
        }
    }
}
