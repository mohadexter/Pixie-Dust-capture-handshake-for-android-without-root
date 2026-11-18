package ma.pixiedust.app.core;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.hardware.usb.UsbDevice;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.DocumentsContract;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.json.JSONArray;
import org.json.JSONObject;

import ma.pixiedust.app.core.Data.AccessPoint;
import ma.pixiedust.app.core.Data.AutoOutcome;
import ma.pixiedust.app.core.Data.Capture;
import ma.pixiedust.app.core.Data.Crack;
import ma.pixiedust.app.core.Data.DriverOverride;
import ma.pixiedust.app.core.Data.DriverStep;
import ma.pixiedust.app.core.Data.ScanOutcome;
import ma.pixiedust.app.core.Data.Stage;
import ma.pixiedust.app.core.Data.Verify;
import ma.pixiedust.app.usb.UsbOtg;

/**
 * Owns the engine session and the observable UI state.
 *
 * <p>All hardware/Python work happens on one background thread ({@code engine}),
 * so two operations can never touch the adapter at the same time. State is
 * published to the main thread and screens re-read it from {@link #snapshot()}
 * style getters after {@link Listener#onState()}.
 */
public final class Repo {

    public interface Listener {
        void onState();
    }

    public interface DriverTestListener {
        void onSteps(List<DriverStep> steps);
    }

    public interface SelfTestListener {
        void onSelfTest(Bridge.SelfTest result);
    }

    private static final Pattern SUGGESTED = Pattern.compile("suggested:\\s*([^)]+)");

    private final Context context;
    private final Prefs prefs;
    private final UsbOtg usb;
    private final Bridge bridge = new Bridge();
    private final HistoryStore history;

    private final ExecutorService engine = Executors.newSingleThreadExecutor(r -> {
        Thread thread = new Thread(r, "pixie-engine");
        thread.setDaemon(true);
        return thread;
    });
    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<Listener> listeners = new CopyOnWriteArrayList<>();

    // ------------------------------------------------------------------- state
    public final List<String> logs = new ArrayList<>();
    public volatile List<AccessPoint> accessPoints = new ArrayList<>();
    /** Live clients per BSSID, refreshed from the Python snapshots every ~0.5 s. */
    public volatile Map<String, List<Data.Client>> liveClients = Collections.emptyMap();
    public volatile boolean scanning;
    public volatile boolean attacking;
    public volatile boolean capturing;
    public volatile Data.Handshake handshake;
    public volatile Stage stage = Stage.USB;
    public volatile PixieError error;
    public volatile Capture capture;
    public volatile Crack crack;
    public volatile Verify verify;
    public volatile String adapterDescription = "";
    public volatile ScanOutcome lastScan;
    public volatile AccessPoint target;
    public volatile int countdown = 30;
    public volatile boolean engineAvailable = true;

    private volatile boolean foreground = true;
    private volatile boolean sessionOpen;
    private volatile String sessionKey;
    private volatile DriverOverride sessionOverride;
    private volatile Future<?> running;
    private volatile String lastChannelSource = "scan";

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            try {
                if (foreground && !scanning && !attacking && !capturing) {
                    if (countdown > 0) {
                        countdown--;
                    } else {
                        countdown = prefs.refreshInterval();
                        if (prefs.autoRefresh()) {
                            UsbDevice device = usb.findAttached();
                            if (device != null && usb.hasPermission(device)) {
                                triggerScan(false);
                            }
                        }
                    }
                    fire();
                }
            } finally {
                main.postDelayed(this, 1000L);
            }
        }
    };

    public Repo(Context context, UsbOtg usb, Prefs prefs) {
        this.context = context.getApplicationContext();
        this.usb = usb;
        this.prefs = prefs;
        this.history = new HistoryStore(this.context);
        usb.setDetachListener(this::handleUsbDetached);
    }

    // ---------------------------------------------------------------- listeners

    public void addListener(Listener listener) {
        if (!listeners.contains(listener)) {
            listeners.add(listener);
        }
    }

    public void removeListener(Listener listener) {
        listeners.remove(listener);
    }

    public void start() {
        engineAvailable = bridge.isAvailable();
        main.post(ticker);
        engine.submit(this::logLibusbSelfTest);
    }

    /** Logs whether the bundled libusb loads, so a packaging problem is visible in logcat. */
    private void logLibusbSelfTest() {
        Bridge.SelfTest result = bridge.selfTest(nativeLibDir());
        if (result.ok) {
            android.util.Log.i("PixieDust", "libusb " + result.version + " loaded from " + result.lib);
        } else {
            android.util.Log.w("PixieDust", "libusb self-test failed: " + result.error);
        }
    }

    public void setForeground(boolean value) {
        foreground = value;
    }

    public void setCountdown(int seconds) {
        countdown = seconds;
        fire();
    }

    public void clearError() {
        error = null;
        fire();
    }

    private void fire() {
        main.post(() -> {
            for (Listener listener : listeners) {
                listener.onState();
            }
        });
    }

    private void postState() {
        for (Listener listener : listeners) {
            listener.onState();
        }
    }

    // ------------------------------------------------------------------- scans

    public void triggerScan(boolean awaitPermission) {
        if (scanning || attacking || capturing) {
            return;
        }
        scanning = true;
        error = null;
        fire();

        Future<?> task = engine.submit(() -> {
            try {
                float timeout = prefs.scanTimeout();
                if (!connectAdapter(null, awaitPermission)) {
                    return;
                }
                ScanOutcome outcome = bridge.scan(timeout, prefs.showAllNetworks(),
                        line -> handleStreamedLog(line, null, null));
                lastScan = outcome;

                List<AccessPoint> sorted = new ArrayList<>();
                for (AccessPoint ap : outcome.aps) {
                    if (prefs.showAllNetworks() || ap.wps) {
                        sorted.add(ap);
                    }
                }
                // Strongest signal first, exactly as requested; the MAC keeps the
                // order stable between two equal readings.
                mergeKnownDeviceInfo(sorted);
                Collections.sort(sorted, (a, b) -> {
                    int bySignal = Integer.compare(b.rssi, a.rssi);
                    if (bySignal != 0) {
                        return bySignal;
                    }
                    return a.bssid.compareTo(b.bssid);
                });
                accessPoints = sorted;
                if (!prefs.showAllNetworks()) {
                    addLog("WPS networks: " + sorted.size() + " of " + outcome.aps.size());
                }

                if (outcome.aps.isEmpty()) {
                    error = emptyScanError(outcome);
                } else {
                    error = null;
                }
            } catch (Throwable t) {
                closeSession();
                error = mapError(message(t));
            } finally {
                scanning = false;
                countdown = prefs.refreshInterval();
                fire();
            }
        });
        running = task;
    }

    /**
     * Keeps the vendor/model line filled on every scan: a value learned once is
     * reused when a later scan misses the WSC information element. New values
     * always win, blanks never overwrite what is already known.
     */
    private void mergeKnownDeviceInfo(List<AccessPoint> aps) {
        Map<String, String[]> rows = new HashMap<>();
        for (AccessPoint ap : aps) {
            String vendor = ap.vendor == null ? "" : ap.vendor.trim();
            String model = ap.model == null ? "" : ap.model.trim();
            if (vendor.isEmpty()) {
                vendor = prefs.knownVendor(ap.bssid);
            }
            if (model.isEmpty()) {
                model = prefs.knownModel(ap.bssid);
            }
            ap.vendor = vendor;
            ap.model = model;
            if (!vendor.isEmpty() || !model.isEmpty()) {
                rows.put(ap.bssid, new String[]{vendor, model});
            }
        }
        prefs.rememberApMeta(rows);
    }

    /** PixieDust needs WPS plus a WPA/WPA2-PSK network to derive the password. */
    private static boolean isPixieCandidate(AccessPoint ap) {
        if (ap == null || !ap.wps) {
            return false;
        }
        String enc = ap.encryption == null ? "" : ap.encryption.toUpperCase(Locale.US);
        return enc.contains("WPA");
    }

    private PixieError emptyScanError(ScanOutcome outcome) {
        if ("zero_raw_frames".equals(outcome.diagnostic)) {
            return PixieError.of(PixieError.Kind.ZERO_FRAMES, outcome.detail);
        }
        if ("no_valid_beacons".equals(outcome.diagnostic)) {
            return PixieError.noBeacons(outcome.rxFrames, outcome.detail);
        }
        return PixieError.of(PixieError.Kind.SCAN_EMPTY, outcome.detail);
    }

    // ------------------------------------------------------------------ attack

    public void startAttack(AccessPoint accessPoint, boolean deep, boolean autoVerify) {
        cancelCurrent();
        target = accessPoint;
        attacking = true;
        stage = Stage.USB;
        logs.clear();
        capture = null;
        crack = null;
        verify = null;
        error = null;
        fire();

        Future<?> task = engine.submit(() -> {
            try {
                if (accessPoint.channel < 1 || accessPoint.channel > 14) {
                    String msg = "Invalid or unknown channel ("
                            + accessPoint.channel + ") for " + accessPoint.bssid
                            + "; rescan or specify a channel between 1 and 14.";
                    addLog(msg);
                    error = PixieError.of(PixieError.Kind.INTERNAL, msg);
                    setStage(Stage.FAILED);
                    return;
                }

                addLog("Target: " + accessPoint.displayName("(hidden)")
                        + "  " + accessPoint.bssid + "  ch " + accessPoint.channel);
                setStage(Stage.USB);
                addLog("Opening the USB Wi-Fi adapter...");
                if (!connectAdapter(null, true)) {
                    setStage(Stage.FAILED);
                    return;
                }
                addLog("Adapter ready: " + adapterDescription);

                setStage(Stage.CAPTURE);
                lastChannelSource = "scan";
                addLog("Capturing M1-M3 on channel " + accessPoint.channel + "...");

                AutoOutcome outcome = bridge.autoAttack(
                        accessPoint.bssid,
                        accessPoint.ssid,
                        accessPoint.channel,
                        defaultModes(),
                        deep,
                        "native",
                        35f,
                        line -> handleStreamedLog(line, null, null),
                        lastChannelSource,
                        autoVerify
                );

                scrubSecrets(outcome.crack == null ? null : outcome.crack.pin,
                        outcome.verify == null ? null : outcome.verify.psk);
                capture = outcome.capture;
                verify = outcome.verify;

                if (outcome.engineError) {
                    String detail = outcome.error != null
                            ? outcome.error
                            : (outcome.detail.isEmpty() ? "PixieDust engine error" : outcome.detail);
                    crack = null;
                    error = PixieError.of(PixieError.Kind.ENGINE, detail);
                    setStage(Stage.FAILED);
                    addLog("Engine error: " + detail);
                    return;
                }

                crack = outcome.crack;
                error = outcomeError(outcome);

                String recoveredPin = outcome.crack == null ? null : outcome.crack.pin;
                String recoveredPsk = outcome.verify == null ? null : outcome.verify.psk;
                if ((recoveredPin != null && !recoveredPin.isEmpty())
                        || (recoveredPsk != null && !recoveredPsk.isEmpty())) {
                    recordCredentials(accessPoint, recoveredPin, recoveredPsk);
                }

                if (outcome.pinRecovered && outcome.crack != null && outcome.crack.pin != null) {
                    setStage(Stage.DONE);
                    if (outcome.verify != null && outcome.verify.ok) {
                        addLog("PIN recovered in " + seconds(outcome.crack.seconds)
                                + " (mode " + safe(outcome.crack.mode) + ") and the PSK was returned.");
                    } else if ("verify_declined".equals(outcome.statusCode)) {
                        addLog("PIN recovered in " + seconds(outcome.crack.seconds)
                                + " (mode " + safe(outcome.crack.mode) + "); live verification was skipped.");
                    } else {
                        addLog("PIN recovered in " + seconds(outcome.crack.seconds)
                                + " (mode " + safe(outcome.crack.mode) + "); verification: "
                                + safe(outcome.statusCode));
                    }
                } else {
                    setStage(Stage.FAILED);
                    addLog("Stopped (" + safe(outcome.statusCode) + "): " + outcome.detail);
                }
            } catch (Throwable t) {
                addLog("Error: " + message(t));
                error = PixieError.of(PixieError.Kind.INTERNAL, message(t));
                setStage(Stage.FAILED);
            } finally {
                attacking = false;
                fire();
            }
        });
        running = task;
    }

    public void verifyPin(AccessPoint accessPoint, String pin) {
        if (accessPoint == null || pin == null || pin.isEmpty()) {
            return;
        }
        attacking = true;
        setStage(Stage.VERIFY);
        error = null;
        fire();

        Future<?> task = engine.submit(() -> {
            try {
                if (accessPoint.channel < 1 || accessPoint.channel > 14) {
                    String msg = "Invalid or unknown channel (" + accessPoint.channel + ").";
                    verify = new Verify();
                    verify.pin = pin;
                    verify.detail = msg;
                    verify.statusCode = "invalid_channel";
                    error = PixieError.verifyRejected(msg, null, "");
                    setStage(Stage.FAILED);
                    return;
                }
                addLog("One WPS transaction on " + accessPoint.bssid + " to obtain the PSK...");
                if (!sessionOpen || !usb.hasConnection()) {
                    if (!connectAdapter(null, true)) {
                        setStage(Stage.FAILED);
                        return;
                    }
                }
                Verify result = bridge.verify(
                        accessPoint.bssid,
                        accessPoint.ssid,
                        accessPoint.channel,
                        pin,
                        lastChannelSource,
                        line -> handleStreamedLog(line, pin, null)
                );
                scrubSecrets(pin, result.psk);
                verify = result;
                if (result.ok && result.hasPsk()) {
                    recordCredentials(accessPoint, pin, result.psk);
                    error = null;
                    addLog("PSK received from the access point.");
                    setStage(Stage.DONE);
                } else {
                    addLog("No PSK returned: " + result.detail);
                    error = verifyError(result);
                    setStage(Stage.FAILED);
                }
            } catch (Throwable t) {
                Verify failed = new Verify();
                failed.pin = pin;
                failed.detail = message(t);
                failed.statusCode = "internal_error";
                verify = failed;
                error = PixieError.of(PixieError.Kind.INTERNAL, message(t));
                setStage(Stage.FAILED);
            } finally {
                attacking = false;
                fire();
            }
        });
        running = task;
    }

    // ------------------------------------------------------------------ handshake

    /**
     * Captures one WPA 4-way handshake for {@code accessPoint}. The radio monitors
     * the AP's channel continuously; when {@code deauth} is on, the same bounded
     * client deauth burst wifit3's campaign uses is sent to provoke a re-handshake.
     * The pcap is published to {@code Download/Handshake pixie} so it is visible in
     * the phone's file manager, not buried under Android/data.
     */
    public void captureHandshake(final AccessPoint accessPoint, final int timeoutSeconds,
                                 final boolean deauth) {
        if (accessPoint == null || scanning || attacking || capturing) {
            return;
        }
        capturing = true;
        handshake = null;
        error = null;
        logs.clear();
        // A fresh capture starts with an empty live table, so devices from an
        // earlier network never look like clients of this one.
        liveClients = Collections.emptyMap();
        fire();

        Future<?> task = engine.submit(() -> {
            try {
                addLog("Monitor capture: " + accessPoint.bssid + "  ch " + accessPoint.channel);
                addLog(deauth
                        ? "Monitor RX stays on; a bounded deauth burst targets the clients seen on this BSSID."
                        : "Monitor RX only: no frame is transmitted and no client is disconnected.");
                if (!connectAdapter(null, true)) {
                    return;
                }
                Data.Handshake result = bridge.captureHandshake(
                        accessPoint.bssid,
                        accessPoint.ssid,
                        accessPoint.channel,
                        Math.max(10, timeoutSeconds),
                        handshakeStagingFolder(),
                        deauth,
                        line -> handleStreamedLog(line, null, null));
                if (result.ok && result.hasFile()) {
                    publishHandshake(result);
                    recordHandshake(accessPoint, result);
                }
                handshake = result;
                if (!result.ok) {
                    error = mapError(result.error);
                } else if (!result.hasFile()) {
                    addLog("No frame captured for this BSSID: nothing was saved.");
                } else {
                    addLog((result.complete ? "Complete handshake saved: " : "Partial capture saved: ")
                            + result.displayPath());
                }
            } catch (Throwable t) {
                Data.Handshake failed = new Data.Handshake();
                failed.error = message(t);
                handshake = failed;
                error = mapError(message(t));
                addLog("Capture error: " + message(t));
            } finally {
                capturing = false;
                fire();
            }
        });
        running = task;
    }

    public void cancelCapture() {
        cancelCurrent();
        capturing = false;
        addLog("Capture stopped by the user.");
        fire();
    }

    /** Private working folder; pcap files are copied out of it right after capture. */
    private String handshakeStagingFolder() {
        return new File(context.getCacheDir(), "handshake").getAbsolutePath();
    }

    /** Default folder name shown in the UI: Download/Hanshake. */
    public static final String HANDSHAKE_FOLDER_NAME = Prefs.DEFAULT_HANDSHAKE_FOLDER;

    /**
     * Folder the user will find in a file manager. When a SAF folder was picked
     * in Settings its display name is returned; otherwise it is the absolute
     * Download/&lt;folder&gt; path.
     */
    public String handshakeFolder() {
        String tree = prefs.handshakeTreeUri();
        if (!tree.isEmpty()) {
            String name = treeDocumentName(Uri.parse(tree));
            return name.isEmpty() ? tree : "Documents/" + name;
        }
        File downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        return new File(downloads, prefs.handshakeFolderName()).getAbsolutePath();
    }

    /**
     * Copies the staged pcap into the chosen public folder. A SAF folder wins when
     * the user picked one; otherwise MediaStore writes Download/&lt;folder&gt; on
     * Android 10+ (no permission needed) and the public folder directly on older
     * releases. On any failure the private path is kept and reported honestly
     * instead of claiming a save that did not happen.
     */
    private void publishHandshake(Data.Handshake result) {
        File src = new File(result.path);
        if (!src.isFile()) {
            return;
        }
        String name = src.getName();
        boolean published = false;
        String tree = prefs.handshakeTreeUri();
        if (!tree.isEmpty()) {
            published = publishToTree(result, src, name, Uri.parse(tree));
        }
        if (!published) {
            published = publishToDownloads(result, src, name);
        }
        if (published && src.delete()) {
            result.path = result.publicPath;
        }
    }

    /** Writes the pcap into the tree the user picked with the system folder picker. */
    private boolean publishToTree(Data.Handshake result, File src, String name, Uri treeUri) {
        try {
            String rootId = DocumentsContract.getTreeDocumentId(treeUri);
            Uri parent = DocumentsContract.buildDocumentUriUsingTree(treeUri, rootId);
            Uri child = DocumentsContract.createDocument(context.getContentResolver(), parent,
                    "application/vnd.tcpdump.pcap", name);
            if (child == null) {
                return false;
            }
            try (InputStream in = new FileInputStream(src);
                 OutputStream out = context.getContentResolver().openOutputStream(child)) {
                if (out == null) {
                    context.getContentResolver().delete(child, null, null);
                    return false;
                }
                copy(in, out);
            }
            String folder = treeDocumentName(treeUri);
            result.publicPath = (folder.isEmpty() ? "Documents" : "Documents/" + folder)
                    + "/" + name;
            result.publicUri = child.toString();
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    /** Public Download/&lt;folder&gt; target, MediaStore on Android 10+ and direct before that. */
    private boolean publishToDownloads(Data.Handshake result, File src, String name) {
        String folderName = prefs.handshakeFolderName();
        String folder = new File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                folderName).getAbsolutePath();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ContentValues values = new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                values.put(MediaStore.MediaColumns.MIME_TYPE, "application/vnd.tcpdump.pcap");
                values.put(MediaStore.MediaColumns.RELATIVE_PATH,
                        Environment.DIRECTORY_DOWNLOADS + "/" + folderName);
                values.put(MediaStore.MediaColumns.IS_PENDING, 1);
                Uri uri = context.getContentResolver()
                        .insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                if (uri == null) {
                    return false;
                }
                try (InputStream in = new FileInputStream(src);
                     OutputStream out = context.getContentResolver().openOutputStream(uri)) {
                    if (out == null) {
                        context.getContentResolver().delete(uri, null, null);
                        return false;
                    }
                    copy(in, out);
                }
                ContentValues done = new ContentValues();
                done.put(MediaStore.MediaColumns.IS_PENDING, 0);
                context.getContentResolver().update(uri, done, null, null);
                result.publicPath = new File(folder, name).getAbsolutePath();
                result.publicUri = uri.toString();
                return true;
            }
            File dir = new File(folder);
            if (!dir.isDirectory() && !dir.mkdirs()) {
                return false;
            }
            File dst = new File(dir, name);
            try (InputStream in = new FileInputStream(src);
                 OutputStream out = new FileOutputStream(dst)) {
                copy(in, out);
            }
            result.publicPath = dst.getAbsolutePath();
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    /** Human-readable name of a SAF folder, used only for display. */
    private String treeDocumentName(Uri treeUri) {
        try {
            Uri doc = DocumentsContract.buildDocumentUriUsingTree(
                    treeUri, DocumentsContract.getTreeDocumentId(treeUri));
            try (Cursor cursor = context.getContentResolver().query(
                    doc, new String[]{DocumentsContract.Document.COLUMN_DISPLAY_NAME},
                    null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    String name = cursor.getString(0);
                    if (name != null && !name.trim().isEmpty()) {
                        return name.trim();
                    }
                }
            }
        } catch (Exception ignored) {
            // fall through to the URI's last segment
        }
        String last = treeUri.getLastPathSegment();
        return last == null ? "" : last;
    }

    private static void copy(InputStream in, OutputStream out) throws java.io.IOException {
        byte[] buffer = new byte[64 * 1024];
        int read;
        while ((read = in.read(buffer)) != -1) {
            out.write(buffer, 0, read);
        }
        out.flush();
    }

    /** Records a really-saved, crackability-checked handshake in the local history. */
    private void recordHandshake(AccessPoint ap, Data.Handshake handshake) {
        HistoryStore.Entry entry = new HistoryStore.Entry();
        entry.type = HistoryStore.TYPE_HANDSHAKE;
        entry.ssid = ap == null ? "" : ap.ssid;
        entry.bssid = ap == null ? "" : ap.bssid;
        entry.vendor = ap == null ? "" : ap.vendor;
        entry.model = ap == null ? "" : ap.model;
        entry.channel = ap == null ? 0 : ap.channel;
        entry.path = handshake.displayPath();
        entry.frames = handshake.frames;
        entry.clients = handshake.clients;
        entry.complete = handshake.complete;
        entry.timestamp = System.currentTimeMillis();
        history.add(entry);
        // Keep the final client table on screen for the result, but drop the
        // scan-list counts so the next scan starts clean.
        List<AccessPoint> copy = new ArrayList<>(accessPoints);
        for (AccessPoint point : copy) {
            point.clients = 0;
        }
        accessPoints = copy;
    }

    /** Records a network whose PIN or password was really recovered. */
    private void recordCredentials(AccessPoint ap, String pin, String psk) {
        if (ap == null) {
            return;
        }
        HistoryStore.Entry entry = new HistoryStore.Entry();
        entry.type = HistoryStore.TYPE_CREDENTIALS;
        entry.ssid = ap.ssid;
        entry.bssid = ap.bssid;
        entry.vendor = ap.vendor;
        entry.model = ap.model;
        entry.channel = ap.channel;
        entry.pin = pin == null ? "" : pin;
        entry.psk = psk == null ? "" : psk;
        entry.complete = true;
        entry.timestamp = System.currentTimeMillis();
        history.add(entry);
    }

    public void cancelAttack() {
        cancelCurrent();
        attacking = false;
        stage = Stage.FAILED;
        addLog("Stopped by the user.");
        fire();
    }

    private void cancelCurrent() {
        Future<?> task = running;
        if (task != null) {
            task.cancel(true);
        }
        bridge.cancelScan();
        engine.submit(this::closeSession);
    }

    // -------------------------------------------------------------- driver test

    public void testDriver(final DriverTestListener listener) {
        engine.submit(() -> {
            List<DriverStep> steps;
            try {
                closeSession();
                UsbDevice device = usb.findAttached();
                if (device == null) {
                    steps = Collections.singletonList(
                            new DriverStep("Find adapter", false, "No USB device on OTG"));
                } else {
                    if (!usb.hasPermission(device)) {
                        usb.awaitPermission(device, 15_000L);
                    }
                    if (!usb.hasPermission(device)) {
                        steps = Collections.singletonList(
                                new DriverStep("USB permission", false, "Denied by the user"));
                    } else {
                        UsbOtg.Opened opened = usb.open(device);
                        if (opened == null) {
                            steps = Collections.singletonList(
                                    new DriverStep("Open USB device", false, "openDevice() returned null"));
                        } else {
                            try {
                                steps = bridge.testDriver(
                                        opened.fd,
                                        device.getVendorId(),
                                        device.getProductId(),
                                        nativeLibDir(),
                                        override()
                                );
                            } finally {
                                usb.close();
                            }
                        }
                    }
                }
            } catch (Throwable t) {
                steps = Collections.singletonList(new DriverStep("Driver test", false, message(t)));
            }
            final List<DriverStep> result = steps;
            main.post(() -> listener.onSteps(result));
        });
    }

    public Data.UsbAdapter currentAdapter() {
        return usb.describe(usb.findAttached());
    }

    /** True while the adapter session (and therefore the raw monitor RX) is up. */
    public boolean isSessionOpen() {
        return sessionOpen;
    }

    /** Runs the libusb self-test on the engine thread; safe to call from the UI. */
    public void selfTest(final SelfTestListener listener) {
        engine.submit(() -> {
            final Bridge.SelfTest result = bridge.selfTest(nativeLibDir());
            main.post(() -> listener.onSelfTest(result));
        });
    }

    public void requestUsbPermission() {
        UsbDevice device = usb.findAttached();
        if (device != null && !usb.hasPermission(device)) {
            engine.submit(() -> usb.awaitPermission(device, 15_000L));
        }
    }

    // ------------------------------------------------------------------ session

    private boolean connectAdapter(DriverOverride override, boolean awaitPermission) {
        UsbDevice device = usb.findAttached();
        if (device == null) {
            closeSession();
            adapterDescription = "";
            error = PixieError.of(PixieError.Kind.NO_DEVICE);
            fire();
            return false;
        }

        if (!usb.hasPermission(device)) {
            if (!awaitPermission) {
                error = PixieError.of(PixieError.Kind.USB_PERMISSION);
                fire();
                return false;
            }
            if (!usb.awaitPermission(device, 15_000L)) {
                error = PixieError.of(PixieError.Kind.USB_PERMISSION);
                fire();
                return false;
            }
        }

        DriverOverride effective = override != null ? override : prefs.driverOverride();
        if (effective != null && !effective.isManual()) {
            effective = null;
        }

        String key = device.getVendorId() + ":" + device.getProductId() + ":" + device.getDeviceName();
        if (sessionOpen && usb.isConnectedTo(device) && key.equals(sessionKey)
                && sameOverride(effective, sessionOverride)) {
            error = null;
            return true;
        }

        // Python/libusb must be torn down before the Android connection is closed.
        closeSession();

        UsbOtg.Opened opened = usb.open(device);
        if (opened == null) {
            error = PixieError.of(PixieError.Kind.INTERFACE_CLAIM);
            fire();
            return false;
        }

        Bridge.StartResult result = bridge.start(
                opened.fd,
                device.getVendorId(),
                device.getProductId(),
                nativeLibDir(),
                effective
        );

        if (!result.ok) {
            closeSession();
            adapterDescription = "";
            String raw = result.error + ": " + result.detail;
            if (!result.suggested.isEmpty()) {
                raw += " (suggested: " + result.suggested + ")";
            }
            error = mapError(raw);
            fire();
            return false;
        }

        sessionOpen = true;
        sessionKey = key;
        sessionOverride = effective;
        adapterDescription = result.adapter;
        error = null;
        fire();
        return true;
    }

    private void closeSession() {
        boolean hadSession = sessionOpen || usb.hasConnection();
        sessionOpen = false;
        sessionKey = null;
        sessionOverride = null;
        if (hadSession) {
            bridge.cancelScan();
            bridge.close();
            usb.close();
        }
    }

    public void handleUsbDetached() {
        main.post(() -> {
            addLog("USB adapter disconnected.");
            bridge.cancelScan();
            Future<?> task = running;
            if (task != null) {
                task.cancel(true);
            }
            engine.submit(this::closeSession);
            scanning = false;
            attacking = false;
            capturing = false;
            stage = Stage.FAILED;
            adapterDescription = "";
            error = PixieError.of(PixieError.Kind.USB_DETACHED);
            postState();
        });
    }

    public void shutdown() {
        main.removeCallbacks(ticker);
        bridge.cancelScan();
        Future<?> task = running;
        if (task != null) {
            task.cancel(true);
        }
        engine.submit(this::closeSession);
        engine.shutdown();
    }

    // ------------------------------------------------------------------- logs

    private void handleStreamedLog(String line, String pin, String psk) {
        if (line == null) {
            return;
        }
        if (line.startsWith("[CLIENTS] ")) {
            applyClientSnapshot(line.substring("[CLIENTS] ".length()));
            return;
        }
        if (line.contains("[STAGE] OFFLINE_SEARCH")) {
            setStage(Stage.OFFLINE);
            return;
        }
        if (line.contains("[STAGE] VERIFY_PIN")) {
            setStage(Stage.VERIFY);
            return;
        }
        if (line.contains("[STAGE] PASSWORD")) {
            setStage(Stage.PASSWORD);
            return;
        }
        addLog(redact(line, pin, psk));
    }

    /**
     * Parses one {@code [CLIENTS] {...}} snapshot from Python (every ~0.5 s) and
     * refreshes the per-network client counts, airodump-ng style. The list is
     * replaced with a new instance so the RecyclerView rebinds and shows the
     * new counts without a full rescan.
     */
    private void applyClientSnapshot(String json) {
        try {
            JSONObject root = new JSONObject(json);
            JSONArray rows = root.optJSONArray("clients");
            Map<String, List<Data.Client>> next = new HashMap<>();
            Map<String, Integer> counts = new HashMap<>();
            if (rows != null) {
                for (int i = 0; i < rows.length(); i++) {
                    JSONObject row = rows.optJSONObject(i);
                    if (row == null) {
                        continue;
                    }
                    String bssid = row.optString("bssid", "").toLowerCase(Locale.US);
                    String mac = row.optString("mac", "").toLowerCase(Locale.US);
                    if (bssid.isEmpty() || mac.isEmpty()) {
                        continue;
                    }
                    Data.Client client = new Data.Client();
                    client.mac = mac;
                    client.rssi = row.optInt("rssi", -100);
                    client.ageS = (float) row.optDouble("age", 0.0);
                    List<Data.Client> list = next.get(bssid);
                    if (list == null) {
                        list = new ArrayList<>();
                        next.put(bssid, list);
                    }
                    list.add(client);
                    Integer count = counts.get(bssid);
                    counts.put(bssid, count == null ? 1 : count + 1);
                }
            }
            for (List<Data.Client> list : next.values()) {
                Collections.sort(list, (a, b) -> Integer.compare(b.rssi, a.rssi));
            }
            liveClients = next;

            List<AccessPoint> copy = new ArrayList<>(accessPoints);
            for (AccessPoint ap : copy) {
                String key = ap.bssid == null ? "" : ap.bssid.toLowerCase(Locale.US);
                Integer count = counts.get(key);
                ap.clients = count == null ? 0 : count;
            }
            accessPoints = copy;
            fire();
        } catch (Exception ignored) {
            // A malformed snapshot must never disturb the scan or the UI.
        }
    }

    /** Live clients seen on {@code bssid} (latest snapshot), newest signal first. */
    public List<Data.Client> clientsFor(String bssid) {
        if (bssid == null) {
            return Collections.emptyList();
        }
        List<Data.Client> list = liveClients.get(bssid.toLowerCase(Locale.US));
        return list == null ? Collections.emptyList() : list;
    }

    /** Local, app-private history of captured handshakes and recovered credentials. */
    public HistoryStore history() {
        return history;
    }

    private void addLog(String line) {
        final String clean = line == null ? "" : line;
        main.post(() -> {
            logs.add(clean);
            while (logs.size() > 500) {
                logs.remove(0);
            }
            postState();
        });
    }

    /** Lets a screen append a plain-language line to the same live log. */
    public void note(String line) {
        addLog(line);
    }

    private void setStage(Stage next) {
        main.post(() -> {
            stage = next;
            postState();
        });
    }

    private void scrubSecrets(String pin, String psk) {
        if ((pin == null || pin.isEmpty()) && (psk == null || psk.isEmpty())) {
            return;
        }
        main.post(() -> {
            for (int i = 0; i < logs.size(); i++) {
                logs.set(i, redact(logs.get(i), pin, psk));
            }
            postState();
        });
    }

    private static String redact(String text, String pin, String psk) {
        String clean = text == null ? "" : text;
        if (psk != null && !psk.isEmpty()) {
            clean = clean.replace(psk, "***");
        }
        if (pin != null && !pin.isEmpty()) {
            clean = clean.replace(pin, "********");
        }
        return clean;
    }

    // ------------------------------------------------------------ error mapping

    public PixieError mapError(String raw) {
        String lower = raw == null ? "" : raw.toLowerCase(Locale.US);
        if (lower.contains("permission")) {
            return PixieError.of(PixieError.Kind.USB_PERMISSION, raw);
        }
        if (lower.contains("driver_mismatch") || lower.contains("mismatch")) {
            Matcher matcher = SUGGESTED.matcher(raw == null ? "" : raw);
            return PixieError.driverMismatch(matcher.find() ? matcher.group(1).trim() : null);
        }
        if (lower.contains("no supported") || lower.contains("no usb device")) {
            return PixieError.of(PixieError.Kind.NO_DEVICE, raw);
        }
        if (lower.contains("interface")) {
            return PixieError.of(PixieError.Kind.WRONG_INTERFACE, raw);
        }
        if (lower.contains("firmware")) {
            return PixieError.of(PixieError.Kind.FIRMWARE, raw);
        }
        if (lower.contains("libusb")) {
            return PixieError.of(PixieError.Kind.LIBUSB, raw);
        }
        if (lower.contains("zerocd") || lower.contains("cd-rom")) {
            return PixieError.of(PixieError.Kind.ZEROCD, raw);
        }
        if (lower.contains("detached") || lower.contains("disconnected")) {
            return PixieError.of(PixieError.Kind.USB_DETACHED, raw);
        }
        if (lower.contains("no_m1") || lower.contains("no reply to m1")) {
            return PixieError.of(PixieError.Kind.NO_M1, raw);
        }
        if (lower.contains("association") || lower.contains("assoc_failed")) {
            return PixieError.of(PixieError.Kind.ASSOC_FAILED, raw);
        }
        if (lower.contains("timeout")) {
            return PixieError.of(PixieError.Kind.M1M3_TIMEOUT, raw);
        }
        if (lower.contains("locked")) {
            return PixieError.of(PixieError.Kind.WPS_LOCKED, raw);
        }
        if (lower.contains("rfkill") || lower.contains("radio switch")) {
            return PixieError.of(PixieError.Kind.RFKILL_OFF, raw);
        }
        if (lower.contains("bringup_failed") || lower.contains("driver")) {
            return PixieError.of(PixieError.Kind.DRIVER_INIT, raw);
        }
        return PixieError.of(PixieError.Kind.INTERNAL, raw);
    }

    private PixieError verifyError(Verify result) {
        if (result.ok) {
            return null;
        }
        if (result.configError != null && result.configError == 15) {
            return PixieError.of(PixieError.Kind.WPS_LOCKED);
        }
        if ("locked".equals(result.statusCode)) {
            return PixieError.of(PixieError.Kind.WPS_LOCKED);
        }
        String status = result.statusCode == null ? "" : result.statusCode;
        switch (status) {
            case "psk_ok":
            case "verify_declined":
                return null;
            case "no_m1":
                return PixieError.of(PixieError.Kind.NO_M1, result.detail);
            case "assoc_failed":
                return PixieError.of(PixieError.Kind.ASSOC_FAILED, result.detail);
            case "pin_ok_no_credential":
                return PixieError.of(PixieError.Kind.PIN_OK_NO_CREDENTIAL);
            case "decrypt_failed":
                return PixieError.of(PixieError.Kind.M7_DECRYPT);
            case "timeout":
                return PixieError.of(PixieError.Kind.VERIFY_TIMEOUT);
            default:
                return PixieError.verifyRejected(result.detail, result.configError, result.configErrorName);
        }
    }

    private PixieError outcomeError(AutoOutcome outcome) {
        if (outcome.engineError) {
            return PixieError.of(PixieError.Kind.ENGINE,
                    outcome.error != null ? outcome.error : outcome.detail);
        }
        String status = outcome.statusCode.isEmpty()
                ? (outcome.verify == null ? "" : outcome.verify.statusCode)
                : outcome.statusCode;
        if ("psk_ok".equals(status) || "verify_declined".equals(status)) {
            return null;
        }
        if (outcome.verify != null && outcome.verify.configError != null
                && outcome.verify.configError == 15) {
            return PixieError.of(PixieError.Kind.WPS_LOCKED);
        }
        if ("locked".equals(status)) {
            return PixieError.of(PixieError.Kind.WPS_LOCKED);
        }
        switch (status) {
            case "pin_not_found_in_session":
                return PixieError.of(PixieError.Kind.OFFLINE_CRACK,
                        outcome.crack == null ? "" : safe(outcome.crack.firstHalf));
            case "no_m1":
                return PixieError.of(PixieError.Kind.NO_M1,
                        outcome.verify == null ? outcome.detail : outcome.verify.detail);
            case "assoc_failed":
                return PixieError.of(PixieError.Kind.ASSOC_FAILED, outcome.detail);
            case "pin_ok_no_credential":
                return PixieError.of(PixieError.Kind.PIN_OK_NO_CREDENTIAL);
            case "decrypt_failed":
                return PixieError.of(PixieError.Kind.M7_DECRYPT);
            case "rejected":
                return PixieError.verifyRejected(
                        outcome.verify == null ? outcome.detail : outcome.verify.detail,
                        outcome.verify == null ? null : outcome.verify.configError,
                        outcome.verify == null ? "" : outcome.verify.configErrorName);
            case "timeout":
                return outcome.pinRecovered
                        ? PixieError.of(PixieError.Kind.VERIFY_TIMEOUT)
                        : PixieError.of(PixieError.Kind.M1M3_TIMEOUT);
            default:
                if (outcome.pinRecovered && outcome.verify != null) {
                    return verifyError(outcome.verify);
                }
                String detail = outcome.error != null
                        ? outcome.error
                        : (outcome.detail.isEmpty() ? "Attack failed" : outcome.detail);
                return mapError(detail);
        }
    }

    // ------------------------------------------------------------------ helpers

    private DriverOverride override() {
        DriverOverride value = prefs.driverOverride();
        return value.isManual() ? value : null;
    }

    private static boolean sameOverride(DriverOverride a, DriverOverride b) {
        if (a == null || b == null) {
            return a == b;
        }
        return a.mode == b.mode
                && eq(a.chipset, b.chipset)
                && eq(a.vid, b.vid)
                && eq(a.pid, b.pid)
                && eq(a.firmwarePath, b.firmwarePath);
    }

    private static boolean eq(Object a, Object b) {
        return a == null ? b == null : a.equals(b);
    }

    private List<String> defaultModes() {
        List<String> modes = new ArrayList<>();
        modes.add("null");
        modes.add("static");
        modes.add("ralink");
        return modes;
    }

    private String nativeLibDir() {
        String dir = context.getApplicationInfo().nativeLibraryDir;
        return dir == null ? "" : dir;
    }

    private static String message(Throwable throwable) {
        String text = throwable.getMessage();
        return text == null || text.isEmpty() ? throwable.getClass().getSimpleName() : text;
    }

    private static String safe(String value) {
        return value == null || value.isEmpty() ? "-" : value;
    }

    private static String seconds(float value) {
        return String.format(Locale.US, "%.1fs", value);
    }
}
