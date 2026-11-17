package ma.pixiedust.app;

import android.app.Application;
import android.content.Context;

import androidx.appcompat.app.AppCompatDelegate;
import androidx.core.os.LocaleListCompat;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.usb.UsbOtg;

public class PixieApp extends Application {

    private static PixieApp instance;

    private Prefs prefs;
    private Repo repo;
    private UsbOtg usb;

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;

        // The design is deliberately light-only so contrast stays predictable.
        AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_NO);

        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
        } catch (Throwable ignored) {
            // Bridge.isAvailable() will report the engine as missing.
        }

        prefs = new Prefs(this);
        String language = prefs.language();
        if (!language.isEmpty()) {
            AppCompatDelegate.setApplicationLocales(
                    LocaleListCompat.forLanguageTags(language));
        }
        usb = new UsbOtg(this);
        repo = new Repo(this, usb, prefs);
        usb.register();
        repo.start();
    }

    public static PixieApp from(Context context) {
        return (PixieApp) context.getApplicationContext();
    }

    public Prefs prefs() {
        return prefs;
    }

    public Repo repo() {
        return repo;
    }

    public UsbOtg usb() {
        return usb;
    }
}
