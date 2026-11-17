package ma.pixiedust.app.ui;

import android.os.Bundle;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.databinding.ActivityDisclaimerBinding;

/** Single upfront consent. Declining quits the app. */
public class DisclaimerActivity extends AppCompatActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ActivityDisclaimerBinding b = ActivityDisclaimerBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        Prefs prefs = PixieApp.from(this).prefs();
        b.btnAccept.setOnClickListener(v -> {
            prefs.setDisclaimerAccepted(true);
            finish();
        });
        b.btnDecline.setOnClickListener(v -> quit());
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                quit();
            }
        });
    }

    private void quit() {
        finishAffinity();
    }
}
