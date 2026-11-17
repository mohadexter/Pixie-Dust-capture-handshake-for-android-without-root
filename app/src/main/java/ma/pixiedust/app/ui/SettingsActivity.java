package ma.pixiedust.app.ui;

import android.content.Intent;
import android.os.Bundle;
import android.text.InputType;
import android.widget.EditText;
import android.widget.FrameLayout;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AppCompatDelegate;
import androidx.core.os.LocaleListCompat;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;

import java.util.List;

import ma.pixiedust.app.PixieApp;
import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Prefs;
import ma.pixiedust.app.core.Repo;
import ma.pixiedust.app.databinding.ActivitySettingsBinding;
import ma.pixiedust.app.usb.Adapters;

/** Scan rhythm, run defaults, language, handshake storage and the driver override. */
public class SettingsActivity extends AppCompatActivity {

    private ActivitySettingsBinding b;
    private Prefs prefs;
    private Repo repo;
    private boolean binding = true;

    /** System folder picker: the chosen tree becomes the handshake folder. */
    private final ActivityResultLauncher<android.net.Uri> folderPicker = registerForActivityResult(
            new ActivityResultContracts.OpenDocumentTree(), uri -> {
                if (uri == null) {
                    return;
                }
                try {
                    getContentResolver().takePersistableUriPermission(uri,
                            Intent.FLAG_GRANT_READ_URI_PERMISSION
                                    | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                } catch (Exception ignored) {
                    // Some providers grant only read access; the write test below decides.
                }
                prefs.setHandshakeTreeUri(uri.toString());
                updateFolderLabel();
                Ui.toast(this, R.string.settings_folder_saved);
            });

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        b = ActivitySettingsBinding.inflate(getLayoutInflater());
        setContentView(b.getRoot());
        Ui.paintSystemBars(this);
        repo = PixieApp.from(this).repo();
        prefs = PixieApp.from(this).prefs();

        b.btnBack.setOnClickListener(v -> finish());
        b.btnDrivers.setOnClickListener(v -> startActivity(new Intent(this, DriversActivity.class)));
        b.btnAbout.setOnClickListener(v -> startActivity(new Intent(this, AboutActivity.class)));

        bindSliders();
        bindSwitches();
        bindLanguage();
        bindChipset();
        bindStorage();

        binding = false;
        updateChipsetLabel();
        updateLanguageLabel();
        updateFolderLabel();
    }

    private void bindSliders() {
        b.scanTimeoutSlider.setValue(prefs.scanTimeout());
        b.refreshSlider.setValue(prefs.refreshInterval());
        updateTimeoutLabel(prefs.scanTimeout());
        updateRefreshLabel(prefs.refreshInterval());

        b.scanTimeoutSlider.addOnChangeListener((slider, value, fromUser) -> {
            int seconds = (int) value;
            updateTimeoutLabel(seconds);
            if (!binding && fromUser) {
                prefs.setScanTimeout(seconds);
            }
        });
        b.refreshSlider.addOnChangeListener((slider, value, fromUser) -> {
            int seconds = (int) value;
            updateRefreshLabel(seconds);
            if (!binding && fromUser) {
                prefs.setRefreshInterval(seconds);
            }
        });
    }

    private void updateTimeoutLabel(int seconds) {
        b.scanTimeoutValue.setText(getString(R.string.settings_seconds, seconds));
    }

    private void updateRefreshLabel(int seconds) {
        b.refreshValue.setText(getString(R.string.settings_seconds, seconds));
    }

    private void bindSwitches() {
        b.switchAuto.setChecked(prefs.autoRefresh());
        b.switchAll.setChecked(prefs.showAllNetworks());
        b.switchKeepOn.setChecked(prefs.keepScreenOn());
        b.switchDeep.setChecked(prefs.deepMode());
        b.switchVerify.setChecked(prefs.liveVerify());

        b.switchAuto.setOnCheckedChangeListener((v, checked) -> prefs.setAutoRefresh(checked));
        b.switchAll.setOnCheckedChangeListener((v, checked) -> prefs.setShowAllNetworks(checked));
        b.switchKeepOn.setOnCheckedChangeListener((v, checked) -> prefs.setKeepScreenOn(checked));
        b.switchDeep.setOnCheckedChangeListener((v, checked) -> prefs.setDeepMode(checked));
        b.switchVerify.setOnCheckedChangeListener((v, checked) -> prefs.setLiveVerify(checked));
    }

    private void bindLanguage() {
        b.btnLanguage.setOnClickListener(v -> {
            final String[] tags = {"", "en", "fr"};
            String[] labels = {
                    getString(R.string.settings_language_system),
                    getString(R.string.lang_en),
                    getString(R.string.lang_fr)
            };
            int checked = 0;
            for (int i = 0; i < tags.length; i++) {
                if (tags[i].equals(prefs.language())) {
                    checked = i;
                    break;
                }
            }
            new MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.settings_language_section)
                    .setSingleChoiceItems(labels, checked, (dialog, which) -> {
                        applyLanguage(tags[which]);
                        dialog.dismiss();
                    })
                    .setNegativeButton(R.string.generic_cancel, null)
                    .show();
        });
    }

    private void applyLanguage(String tag) {
        prefs.setLanguage(tag);
        AppCompatDelegate.setApplicationLocales(tag.isEmpty()
                ? LocaleListCompat.getEmptyLocaleList()
                : LocaleListCompat.forLanguageTags(tag));
        updateLanguageLabel();
    }

    private void updateLanguageLabel() {
        String tag = prefs.language();
        if (tag.isEmpty()) {
            b.languageValue.setText(R.string.settings_language_system);
        } else if ("fr".equals(tag)) {
            b.languageValue.setText(R.string.lang_fr);
        } else {
            b.languageValue.setText(R.string.lang_en);
        }
    }

    // ------------------------------------------------------ handshake storage

    private void bindStorage() {
        b.btnHandshakeFolder.setOnClickListener(v -> chooseFolder());
    }

    private void updateFolderLabel() {
        b.handshakePathValue.setText(repo.handshakeFolder());
    }

    private void chooseFolder() {
        String[] items = {
                getString(R.string.settings_folder_default),
                getString(R.string.settings_folder_pick),
                getString(R.string.settings_folder_custom)
        };
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_storage_section)
                .setItems(items, (dialog, which) -> {
                    if (which == 0) {
                        prefs.setHandshakeTreeUri("");
                        prefs.setHandshakeFolderName(Prefs.DEFAULT_HANDSHAKE_FOLDER);
                        updateFolderLabel();
                    } else if (which == 1) {
                        try {
                            folderPicker.launch(null);
                        } catch (Exception e) {
                            Ui.toast(this, R.string.settings_folder_pick_failed);
                        }
                    } else {
                        askFolderName();
                    }
                })
                .setNegativeButton(R.string.generic_cancel, null)
                .show();
    }

    private void askFolderName() {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT);
        input.setText(prefs.handshakeFolderName());
        input.setSelection(input.getText().length());
        int pad = (int) Ui.dp(this, 20f);
        FrameLayout box = new FrameLayout(this);
        box.setPadding(pad, pad / 2, pad, 0);
        box.addView(input);
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_folder_name_title)
                .setView(box)
                .setNegativeButton(R.string.generic_cancel, null)
                .setPositiveButton(R.string.settings_folder_save, (dialog, which) -> {
                    String name = input.getText().toString().trim();
                    if (name.isEmpty()
                            || name.contains("/")
                            || name.contains("\\")
                            || name.contains("..")) {
                        Ui.toast(this, R.string.settings_folder_invalid);
                        return;
                    }
                    prefs.setHandshakeTreeUri("");
                    prefs.setHandshakeFolderName(name);
                    updateFolderLabel();
                })
                .show();
    }

    private void bindChipset() {
        b.btnChipset.setOnClickListener(v -> chooseChipset());
        b.btnReset.setOnClickListener(v -> {
            prefs.resetDriverOverride();
            updateChipsetLabel();
            Ui.toast(this, R.string.settings_chipset_auto);
        });
    }

    private void chooseChipset() {
        final List<String> chipsets = Adapters.chipsets();
        String[] labels = new String[chipsets.size() + 1];
        labels[0] = getString(R.string.settings_chipset_auto);
        int checked = 0;
        String current = prefs.driverOverride().chipset;
        for (int i = 0; i < chipsets.size(); i++) {
            labels[i + 1] = chipsets.get(i);
            if (chipsets.get(i).equalsIgnoreCase(current == null ? "" : current)) {
                checked = i + 1;
            }
        }
        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.settings_chipset)
                .setSingleChoiceItems(labels, checked, (dialog, which) -> {
                    if (which == 0) {
                        prefs.setChipsetOverride(null);
                    } else {
                        prefs.setChipsetOverride(chipsets.get(which - 1));
                    }
                    updateChipsetLabel();
                    dialog.dismiss();
                })
                .setNegativeButton(R.string.generic_cancel, null)
                .show();
    }

    private void updateChipsetLabel() {
        String chipset = prefs.driverOverride().chipset;
        b.btnChipset.setText(chipset == null || chipset.isEmpty()
                ? getString(R.string.settings_chipset_auto)
                : chipset);
    }
}
