package ma.pixiedust.app.ui;

import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.OvershootInterpolator;

import androidx.appcompat.app.AppCompatActivity;

import ma.pixiedust.app.databinding.ActivitySplashBinding;

/**
 * A short branded opening: the app icon pops in, the name rises, then the scan
 * screen takes over. Purely cosmetic, and always finishes so the app is never
 * held hostage by the animation.
 */
public class SplashActivity extends AppCompatActivity {

    private static final long HOLD_MS = 1050L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable open = this::openScan;
    private boolean launched;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ActivitySplashBinding b = ActivitySplashBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);

        b.splashLogo.setAlpha(0f);
        b.splashLogo.setScaleX(0.6f);
        b.splashLogo.setScaleY(0.6f);
        b.splashLogo.animate()
                .alpha(1f)
                .scaleX(1f)
                .scaleY(1f)
                .setDuration(620L)
                .setInterpolator(new OvershootInterpolator(1.2f))
                .start();

        b.splashName.setAlpha(0f);
        b.splashName.setTranslationY(Ui.dp(this, 12f));
        b.splashName.animate()
                .alpha(1f)
                .translationY(0f)
                .setStartDelay(160L)
                .setDuration(420L)
                .setInterpolator(new DecelerateInterpolator())
                .start();

        handler.postDelayed(open, HOLD_MS);
    }

    private void openScan() {
        if (launched) {
            return;
        }
        launched = true;
        Intent intent = new Intent(this, ScanActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(intent);
        overridePendingTransition(0, android.R.anim.fade_out);
        finish();
    }

    @Override
    public void onBackPressed() {
        handler.removeCallbacks(open);
        openScan();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(open);
        super.onDestroy();
    }
}
