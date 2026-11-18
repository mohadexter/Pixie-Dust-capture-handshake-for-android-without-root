package ma.pixiedust.app.ui;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import ma.pixiedust.app.R;
import ma.pixiedust.app.core.Data;
import ma.pixiedust.app.core.KnownModels;
import ma.pixiedust.app.databinding.ItemApBinding;

/** Flat list of access points. The list object only changes after a scan. */
public class ApAdapter extends RecyclerView.Adapter<ApAdapter.VH> {

    public interface OnOpen {
        void onOpen(Data.AccessPoint ap);
    }

    private final OnOpen onOpen;
    private final String hidden;
    private final Set<String> animated = new HashSet<>();
    private List<Data.AccessPoint> items = Collections.emptyList();

    public ApAdapter(Context context, OnOpen onOpen) {
        this.onOpen = onOpen;
        this.hidden = context.getString(R.string.scan_hidden);
    }

    public void submit(List<Data.AccessPoint> list) {
        if (list == null || list == items) {
            return;
        }
        items = list;
        animated.clear();
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public VH onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemApBinding binding = ItemApBinding.inflate(
                LayoutInflater.from(parent.getContext()), parent, false);
        return new VH(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull VH holder, int position) {
        Data.AccessPoint ap = items.get(position);
        ItemApBinding b = holder.binding;
        Context context = b.getRoot().getContext();

        b.ssidText.setText(ap.displayName(hidden));
        b.signalBars.setRssi(ap.rssi);

        StringBuilder meta = new StringBuilder();
        if (!ap.encryption.isEmpty()) {
            meta.append(ap.encryption).append("  \u00b7  ");
        }
        meta.append(context.getString(R.string.scan_ch, ap.channel))
                .append("  \u00b7  ")
                .append(context.getString(R.string.scan_dbm, ap.rssi));
        if (ap.wps && !ap.wpsVersion.isEmpty()) {
            meta.append("  \u00b7  WPS ").append(ap.wpsVersion);
        }
        b.metaText.setText(meta.toString());

        String vendor = ap.vendor == null ? "" : ap.vendor.trim();
        String model = ap.model == null ? "" : ap.model.trim();
        String device = vendor;
        if (!model.isEmpty()) {
            device = vendor.isEmpty()
                    ? model
                    : context.getString(R.string.device_vendor_model, vendor, model);
        }
        if (device.isEmpty()) {
            b.vendorText.setVisibility(View.GONE);
        } else {
            b.vendorText.setVisibility(View.VISIBLE);
            b.vendorText.setText(device);
        }

        // A model from the offline known list: the network name goes green and a
        // small "Pixie" pill sits next to WPS, so the target stands out in a scan.
        boolean pixieModel = KnownModels.matches(context, model);
        b.ssidText.setTextColor(context.getColor(pixieModel ? R.color.green : R.color.ink));
        b.pixiePill.setVisibility(pixieModel && ap.wps ? View.VISIBLE : View.GONE);

        b.wpsPill.setVisibility(ap.wps ? android.view.View.VISIBLE : android.view.View.GONE);
        b.lockPill.setVisibility(ap.locked ? android.view.View.VISIBLE : android.view.View.GONE);

        if (ap.clients > 0) {
            b.clientsPill.setVisibility(View.VISIBLE);
            b.clientsPill.setText(ap.clients == 1
                    ? context.getString(R.string.scan_clients_one)
                    : context.getString(R.string.scan_clients, ap.clients));
        } else {
            b.clientsPill.setVisibility(View.GONE);
        }

        b.getRoot().setOnClickListener(v -> onOpen.onOpen(ap));

        // First appearance of each BSSID: a short fade/rise. Re-binds on scroll
        // reuse the same identity, so they don't re-animate.
        View root = b.getRoot();
        if (animated.add(ap.bssid)) {
            root.setAlpha(0f);
            root.setTranslationY(Ui.dp(context, 8f));
            root.animate()
                    .alpha(1f)
                    .translationY(0f)
                    .setStartDelay(Math.min(position, 7) * 35L)
                    .setDuration(260L)
                    .start();
        } else {
            root.setAlpha(1f);
            root.setTranslationY(0f);
        }
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static final class VH extends RecyclerView.ViewHolder {
        final ItemApBinding binding;

        VH(ItemApBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }
    }
}
