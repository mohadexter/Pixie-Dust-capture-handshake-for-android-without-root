package ma.pixiedust.app.ui;

import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.widget.TextViewCompat;

import com.google.android.material.card.MaterialCardView;
import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import java.text.DateFormat;
import java.util.Date;
import java.util.List;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.HistoryStore;
import ma.pixiedust.app.databinding.ActivityHistoryBinding;

/** Private on-device record of verified captures and recovered credentials. */
public class HistoryActivity extends AppCompatActivity {

    private ActivityHistoryBinding b;
    private HistoryStore history;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivityHistoryBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);
        history = PixieApp.from(this).repo().history();

        b.btnBack.setOnClickListener(v -> finish());
        b.btnClear.setOnClickListener(v -> confirmClear());
        render();
    }

    @Override
    protected void onResume() {
        super.onResume();
        render();
    }

    private void confirmClear() {
        if (history.all().isEmpty()) {
            return;
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.history_clear_confirm)
                .setMessage(R.string.history_clear_body)
                .setNegativeButton(R.string.generic_cancel, null)
                .setPositiveButton(R.string.history_clear, (dialog, which) -> {
                    history.clear();
                    render();
                })
                .show();
    }

    private void render() {
        if (b == null) {
            return;
        }
        List<HistoryStore.Entry> entries = history.all();
        b.entries.removeAllViews();
        boolean empty = entries.isEmpty();
        b.emptyState.setVisibility(empty ? View.VISIBLE : View.GONE);
        b.btnClear.setEnabled(!empty);
        b.entries.setVisibility(empty ? View.GONE : View.VISIBLE);
        for (HistoryStore.Entry entry : entries) {
            b.entries.addView(createEntry(entry));
        }
    }

    private View createEntry(HistoryStore.Entry entry) {
        MaterialCardView card = new MaterialCardView(this);
        LinearLayout.LayoutParams cardParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        cardParams.bottomMargin = (int) Ui.dp(this, 10f);
        card.setLayoutParams(cardParams);
        card.setRadius(Ui.dp(this, 16f));
        card.setCardElevation(0f);
        card.setStrokeWidth((int) Ui.dp(this, 1f));
        card.setStrokeColor(getColor(R.color.line));
        card.setCardBackgroundColor(getColor(R.color.surface));
        card.setContentPadding((int) Ui.dp(this, 16f), (int) Ui.dp(this, 14f),
                (int) Ui.dp(this, 16f), (int) Ui.dp(this, 14f));

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        card.addView(content);

        TextView type = text(getString(entry.isHandshake()
                ? R.string.history_type_handshake : R.string.history_type_credentials),
                R.style.TextAppearance_PixieDust_Caption);
        type.setTextColor(getColor(R.color.indigo));
        content.addView(type);

        String name = entry.ssid == null || entry.ssid.trim().isEmpty()
                ? entry.bssid : entry.ssid;
        TextView title = text(name, R.style.TextAppearance_PixieDust_Title);
        title.setTextIsSelectable(true);
        content.addView(title);

        TextView network = text(entry.bssid, R.style.TextAppearance_PixieDust_Mono);
        network.setTextIsSelectable(true);
        content.addView(network);

        String manufacturer = joinNonEmpty(entry.vendor, entry.model);
        if (!manufacturer.isEmpty()) {
            content.addView(text(manufacturer, R.style.TextAppearance_PixieDust_Caption));
        }
        if (entry.channel > 0) {
            content.addView(text(getString(R.string.scan_ch, entry.channel),
                    R.style.TextAppearance_PixieDust_Caption));
        }
        content.addView(text(DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
                        .format(new Date(entry.timestamp)),
                R.style.TextAppearance_PixieDust_Caption));

        if (entry.isHandshake()) {
            content.addView(text(getString(R.string.history_meta, entry.frames, entry.clients),
                    R.style.TextAppearance_PixieDust_Caption));
            if (!TextUtils.isEmpty(entry.path)) {
                TextView file = text(getString(R.string.history_path, entry.path),
                        R.style.TextAppearance_PixieDust_Mono);
                file.setTextIsSelectable(true);
                file.setOnClickListener(v -> Ui.copy(this, entry.path, R.string.history_copied));
                content.addView(file);
            }
        } else {
            // Each recovered value is a separate copy affordance; no empty credential row.
            if (!TextUtils.isEmpty(entry.pin)) {
                TextView pin = text(getString(R.string.history_pin, entry.pin),
                        R.style.TextAppearance_PixieDust_Mono);
                pin.setTextIsSelectable(true);
                pin.setOnClickListener(v -> Ui.copy(this, entry.pin, R.string.history_copied));
                content.addView(pin);
            }
            if (!TextUtils.isEmpty(entry.psk)) {
                TextView psk = text(getString(R.string.history_psk, entry.psk),
                        R.style.TextAppearance_PixieDust_Mono);
                psk.setTextIsSelectable(true);
                psk.setOnClickListener(v -> Ui.copy(this, entry.psk, R.string.history_copied));
                content.addView(psk);
            }
        }
        return card;
    }

    private TextView text(CharSequence value, int appearance) {
        TextView view = new TextView(this);
        TextViewCompat.setTextAppearance(view, appearance);
        view.setText(value);
        view.setTextDirection(View.TEXT_DIRECTION_FIRST_STRONG);
        view.setPadding(0, (int) Ui.dp(this, 2f), 0, (int) Ui.dp(this, 2f));
        return view;
    }

    private static String joinNonEmpty(String first, String second) {
        String a = first == null ? "" : first.trim();
        String b = second == null ? "" : second.trim();
        if (a.isEmpty()) return b;
        if (b.isEmpty() || a.equalsIgnoreCase(b)) return a;
        return a + " · " + b;
    }
}
