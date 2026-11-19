package ma.pixiedust.app.ui;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;

import androidx.appcompat.app.AppCompatActivity;

import java.util.function.IntConsumer;

import ma.pixiedust.app.R;
import ma.pixiedust.app.databinding.ActivitySupportBinding;
import ma.pixiedust.app.databinding.ViewDonateRowBinding;

/** Donation addresses with one-tap copy, plus the Telegram support channel. */
public class SupportActivity extends AppCompatActivity {

    private ActivitySupportBinding b;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivitySupportBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        b.btnBack.setOnClickListener(v -> finish());
        b.btnCopyBtc.setOnClickListener(v -> copy(R.string.support_btc_address));
        b.btnCopyEth.setOnClickListener(v -> copy(R.string.support_eth_address));
        b.btnCopyLtc.setOnClickListener(v -> copy(R.string.support_ltc_address));
        b.btnCopySol.setOnClickListener(v -> copy(R.string.support_sol_address));
        b.btnCopyTrx.setOnClickListener(v -> copy(R.string.support_trx_address));
        b.btnTelegram.setOnClickListener(v -> openTelegram());
        bindDonations(b.donateRow, this::copy);
    }

    /** One-tap copy for the shared coin strip (About reuses this). */
    static void bindDonations(ViewDonateRowBinding row, IntConsumer onCopy) {
        row.coinBtc.setOnClickListener(v -> onCopy.accept(R.string.support_btc_address));
        row.coinEth.setOnClickListener(v -> onCopy.accept(R.string.support_eth_address));
        row.coinLtc.setOnClickListener(v -> onCopy.accept(R.string.support_ltc_address));
        row.coinSol.setOnClickListener(v -> onCopy.accept(R.string.support_sol_address));
        row.coinTrx.setOnClickListener(v -> onCopy.accept(R.string.support_trx_address));
    }

    private void copy(int addressRes) {
        String address = getString(addressRes);
        ClipboardManager clipboard =
                (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(ClipData.newPlainText("Pixie Dust", address));
        }
        Ui.toast(this, R.string.support_copied);
    }

    private void openTelegram() {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW,
                    Uri.parse("https://t.me/PixieDustapp")));
        } catch (Exception ignored) {
            Ui.toast(this, R.string.support_no_browser);
        }
    }
}
