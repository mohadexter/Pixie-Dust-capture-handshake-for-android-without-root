package ma.pixiedust.app.ui;

import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Bundle;

import androidx.appcompat.app.AppCompatActivity;

import ma.pixiedust.app.R;
import ma.pixiedust.app.databinding.ActivityAboutBinding;

/** Static identity, guarantees, and licence. */
public class AboutActivity extends AppCompatActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ActivityAboutBinding b = ActivityAboutBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        b.btnBack.setOnClickListener(v -> finish());
        b.btnClose.setOnClickListener(v -> finish());
        b.btnReleaseNotes.setOnClickListener(v -> WhatsNewDialog.showReleaseNotes(this));
        b.btnTelegramSupport.setOnClickListener(v -> {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW,
                        Uri.parse("https://t.me/PixieDustapp")));
            } catch (Exception ignored) {
                Ui.toast(this, R.string.support_no_browser);
            }
        });
        b.btnSupportProject.setOnClickListener(v ->
                startActivity(new Intent(this, SupportActivity.class)));
        SupportActivity.bindDonations(b.donateRow, addressRes ->
                Ui.copy(this, getString(addressRes), R.string.support_copied));
        b.versionText.setText(getString(R.string.about_version, versionName()));
    }

    private String versionName() {
        try {
            PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
            String name = info.versionName;
            return name == null || name.isEmpty() ? "1.0.0" : name;
        } catch (Exception e) {
            return "1.0.0";
        }
    }
}
