package ma.pixiedust.app.ui;

import android.app.Activity;
import android.content.Intent;
import android.view.View;
import android.view.ViewGroup;

import com.google.android.material.bottomsheet.BottomSheetDialog;

import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.databinding.SheetNetworkBinding;

/** Small panel shown when a network is tapped: details + two operations. */
public final class NetworkSheet {

    public static void show(Activity activity, Data.AccessPoint ap) {
        BottomSheetDialog dialog = new BottomSheetDialog(activity);
        SheetNetworkBinding b = SheetNetworkBinding.inflate(activity.getLayoutInflater());
        dialog.setContentView(b.getRoot());

        b.sheetSsid.setText(ap.displayName(activity.getString(R.string.scan_hidden)));
        b.sheetBssid.setText(ap.bssid);
        String vendor = ap.vendor == null ? "" : ap.vendor.trim();
        String model = ap.model == null ? "" : ap.model.trim();
        String device = vendor.isEmpty()
                ? activity.getString(R.string.result_vendor_unknown)
                : vendor;
        if (!model.isEmpty()) {
            device = activity.getString(R.string.device_vendor_model, device, model);
        }
        b.sheetVendor.setText(device);

        b.sheetType.setText(ap.encryption.isEmpty() ? "—" : ap.encryption);
        b.sheetChannel.setText(activity.getString(R.string.scan_ch, ap.channel));
        b.sheetWps.setText(ap.wps
                ? activity.getString(R.string.details_wps_on, ap.wpsVersion)
                : "WPS ✕");
        b.sheetClients.setText(ap.clients > 0
                ? activity.getString(R.string.details_clients, ap.clients)
                : activity.getString(R.string.details_clients_none));

        boolean capturable = ap.channel >= 1 && ap.channel <= 14;
        b.cardSheetCapture.setEnabled(capturable);
        b.cardSheetCapture.setAlpha(capturable ? 1f : 0.45f);
        b.cardSheetCapture.setOnClickListener(v -> {
            if (!capturable) {
                return;
            }
            dialog.dismiss();
            HandshakeActivity.start(activity, ap);
        });

        boolean attackable = ap.canAttack();
        b.cardSheetAttack.setEnabled(attackable);
        b.cardSheetAttack.setAlpha(attackable ? 1f : 0.45f);
        b.cardSheetAttack.setOnClickListener(v -> {
            if (!attackable) {
                Ui.toast(activity, R.string.details_blocked_no_wps);
                return;
            }
            dialog.dismiss();
            Intent intent = new Intent(activity, DetailsActivity.class);
            Ui.putAp(intent, ap);
            activity.startActivity(intent);
        });

        b.btnSheetClose.setOnClickListener(v -> dialog.dismiss());
        dialog.show();

        // Both cards must share one height whatever the text wraps to on this
        // screen width. They are measured with their own content first, then the
        // shorter one is stretched to the taller one right before the first draw.
        final View capture = b.cardSheetCapture;
        final View attack = b.cardSheetAttack;
        final View root = b.getRoot();
        root.getViewTreeObserver().addOnPreDrawListener(
                new android.view.ViewTreeObserver.OnPreDrawListener() {
                    @Override
                    public boolean onPreDraw() {
                        int height = Math.max(capture.getMeasuredHeight(),
                                attack.getMeasuredHeight());
                        if (height <= 0) {
                            return true;
                        }
                        android.view.ViewTreeObserver observer = root.getViewTreeObserver();
                        if (observer.isAlive()) {
                            observer.removeOnPreDrawListener(this);
                        }
                        for (View card : new View[]{capture, attack}) {
                            ViewGroup.LayoutParams lp = card.getLayoutParams();
                            if (lp.height != height) {
                                lp.height = height;
                                card.setLayoutParams(lp);
                            }
                        }
                        return true;
                    }
                });
    }
}
