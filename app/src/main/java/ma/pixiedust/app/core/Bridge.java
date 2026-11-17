package ma.pixiedust.app.core;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import ma.pixiedust.app.core.Data.AutoOutcome;
import ma.pixiedust.app.core.Data.Capture;
import ma.pixiedust.app.core.Data.Crack;
import ma.pixiedust.app.core.Data.DriverOverride;
import ma.pixiedust.app.core.Data.DriverStep;
import ma.pixiedust.app.core.Data.ScanOutcome;
import ma.pixiedust.app.core.Data.Verify;

/**
 * Thin, blocking wrapper around the Python engine ({@code pixie_android.bridge}).
 * Every call here is made from the repository's single background thread, so
 * the engine never sees two concurrent hardware operations.
 */
public final class Bridge {

    /** Python needs a callable; we hand it a Java object through android_cb.wrap(). */
    public interface LogSink {
        void onLog(String line);
    }

    public static final class StartResult {
        public boolean ok;
        public String adapter = "";
        public String chipset = "";
        public String error = "";
        public String detail = "";
        public String suggested = "";
    }

    /** Result of loading the bundled libusb without touching an adapter. */
    public static final class SelfTest {
        public boolean ok;
        public String lib = "";
        public String version = "";
        public String error = "";
    }

    private static final String MODULE = "pixie_android.bridge";

    public boolean isAvailable() {
        try {
            return Python.isStarted() && module() != null;
        } catch (Throwable t) {
            return false;
        }
    }

    private PyObject module() {
        return Python.getInstance().getModule(MODULE);
    }

    private PyObject python() {
        return Python.getInstance().getModule("builtins");
    }

    private PyObject callback(LogSink sink) {
        if (sink == null) {
            return null;
        }
        return Python.getInstance()
                .getModule("pixie_android.android_cb")
                .callAttr("wrap", sink);
    }

    // ------------------------------------------------------------------ session

    public StartResult start(int fd, int vid, int pid, String nativeLibDir, DriverOverride override) {
        StartResult out = new StartResult();
        try {
            PyObject res = module().callAttr("start", fd, vid, pid, nativeLibDir, overrideMap(override, true));
            out.ok = bool(res.callAttr("get", "ok"));
            out.adapter = orEmpty(str(res.callAttr("get", "adapter")));
            out.chipset = orEmpty(str(res.callAttr("get", "chipset")));
            out.error = orEmpty(str(res.callAttr("get", "error")));
            out.detail = orEmpty(str(res.callAttr("get", "detail")));
            out.suggested = orEmpty(str(res.callAttr("get", "suggested")));
        } catch (Throwable t) {
            out.ok = false;
            out.error = "bringup_failed";
            out.detail = t.getMessage() == null ? t.getClass().getSimpleName() : t.getMessage();
        }
        return out;
    }

    public void close() {
        try {
            module().callAttr("close");
        } catch (Throwable ignored) {
            // The session is already gone or Python was never started.
        }
    }

    public void cancelScan() {
        try {
            module().callAttr("cancel_scan");
        } catch (Throwable ignored) {
            // nothing to cancel
        }
    }

    /** Loads libusb (init + exit) so a packaging problem shows up before a scan. */
    public SelfTest selfTest(String nativeLibDir) {
        SelfTest out = new SelfTest();
        try {
            PyObject res = module().callAttr("usb_selftest", nativeLibDir);
            out.ok = bool(res.callAttr("get", "ok"));
            out.lib = orEmpty(str(res.callAttr("get", "lib")));
            out.version = orEmpty(str(res.callAttr("get", "version")));
            out.error = orEmpty(str(res.callAttr("get", "error")));
        } catch (Throwable t) {
            out.ok = false;
            out.error = t.getMessage() == null ? t.getClass().getSimpleName() : t.getMessage();
        }
        return out;
    }

    // --------------------------------------------------------------------- scan

    public ScanOutcome scan(float timeoutSeconds, boolean includeAll, LogSink sink) {
        PyObject res = module().callAttr("scan", timeoutSeconds, includeAll, callback(sink));
        if (!bool(res.callAttr("get", "ok"))) {
            String err = str(res.callAttr("get", "error"));
            String detail = orEmpty(str(res.callAttr("get", "detail")));
            throw new IllegalStateException(err != null ? err : (detail.isEmpty() ? "scan_failed" : detail));
        }

        ScanOutcome out = new ScanOutcome();
        out.diagnostic = orEmpty(str(res.callAttr("get", "diagnostic")));
        if (out.diagnostic.isEmpty()) {
            out.diagnostic = "ok";
        }
        out.detail = orEmpty(str(res.callAttr("get", "detail")));
        out.rxFrames = intOr(res.callAttr("get", "rx_frames"), 0);
        out.rxBursts = intOr(res.callAttr("get", "rx_bursts"), 0);
        out.beaconCount = intOr(res.callAttr("get", "beacon_count"), 0);
        out.callbackErrors = intOr(res.callAttr("get", "callback_errors"), 0);
        out.elapsedS = floatOr(res.callAttr("get", "elapsed_s"), 0f);

        PyObject channels = res.callAttr("get", "channels");
        if (channels != null && !isNone(channels)) {
            for (PyObject ch : channels.asList()) {
                Integer value = intOrNull(ch);
                if (value != null) {
                    out.channels.add(value);
                }
            }
        }

        PyObject aps = res.callAttr("get", "aps");
        if (aps != null && !isNone(aps)) {
            for (PyObject ap : aps.asList()) {
                Data.AccessPoint point = new Data.AccessPoint();
                point.bssid = orEmpty(str(ap.callAttr("get", "bssid")));
                point.ssid = orEmpty(str(ap.callAttr("get", "ssid")));
                point.channel = intOr(ap.callAttr("get", "channel"), 0);
                point.rssi = intOr(ap.callAttr("get", "rssi"), -70);
                point.encryption = orEmpty(str(ap.callAttr("get", "encryption")));
                point.wps = bool(ap.callAttr("get", "wps"));
                point.wpsVersion = orEmpty(str(ap.callAttr("get", "wps_version")));
                point.locked = bool(ap.callAttr("get", "locked"));
                point.vendor = orEmpty(str(ap.callAttr("get", "vendor")));
                point.model = orEmpty(str(ap.callAttr("get", "model")));
                point.clients = intOr(ap.callAttr("get", "clients"), 0);
                out.aps.add(point);
            }
        }
        return out;
    }

    // -------------------------------------------------------------- handshake

    public Data.Handshake captureHandshake(String bssid, String ssid, int channel, float timeout,
                                           String folder, boolean deauth, LogSink sink) {
        PyObject res = module().callAttr(
                "capture_handshake",
                bssid,
                ssid,
                channel,
                timeout,
                folder,
                deauth,
                3,
                3,
                4,
                callback(sink));
        Data.Handshake out = new Data.Handshake();
        out.ok = bool(res.callAttr("get", "ok"));
        out.complete = bool(res.callAttr("get", "complete"));
        out.valid = bool(res.callAttr("get", "valid"));
        out.validPairs = intOr(res.callAttr("get", "valid_pairs"), 0);
        out.clientMac = orEmpty(str(res.callAttr("get", "client_mac")));
        out.pair = orEmpty(str(res.callAttr("get", "pair")));
        out.path = orEmpty(str(res.callAttr("get", "path")));
        out.frames = intOr(res.callAttr("get", "frames"), 0);
        out.eapolFrames = intOr(res.callAttr("get", "eapol_frames"), 0);
        out.clients = intOr(res.callAttr("get", "clients"), 0);
        out.elapsedS = floatOr(res.callAttr("get", "elapsed_s"), 0f);
        out.deauthSent = intOr(res.callAttr("get", "deauth_sent"), 0);
        out.deauthAcked = intOr(res.callAttr("get", "deauth_acked"), 0);
        out.deauthBursts = intOr(res.callAttr("get", "deauth_bursts"), 0);
        out.notes = stringList(res.callAttr("get", "notes"));
        out.error = orEmpty(str(res.callAttr("get", "error")));
        PyObject messages = res.callAttr("get", "messages");
        if (messages != null && !isNone(messages)) {
            for (PyObject item : messages.asList()) {
                Integer value = intOrNull(item);
                if (value != null) {
                    out.messages.add(value);
                }
            }
        }
        return out;
    }

    // -------------------------------------------------------------- auto attack

    public AutoOutcome autoAttack(String bssid, String ssid, int channel, List<String> modes,
                                  boolean deep, String engine, float timeout, LogSink sink,
                                  String channelSource, boolean autoVerify) {
        PyObject res = module().callAttr(
                "auto_attack",
                bssid,
                ssid,
                channel,
                modes.toArray(new String[0]),
                deep,
                engine,
                timeout,
                callback(sink),
                channelSource,
                autoVerify
        );

        AutoOutcome out = new AutoOutcome();
        out.ok = bool(res.callAttr("get", "ok"));
        out.pinRecovered = bool(res.callAttr("get", "pin_recovered"));
        out.statusCode = orEmpty(str(res.callAttr("get", "status_code")));
        out.flow = orEmpty(str(res.callAttr("get", "flow")));
        out.assocCount = intOr(res.callAttr("get", "assoc_count"), 0);
        out.detail = orEmpty(str(res.callAttr("get", "detail")));
        out.engineError = bool(res.callAttr("get", "engine_error"));
        out.error = str(res.callAttr("get", "error"));

        String pin = str(res.callAttr("get", "pin"));
        String firstHalf = str(res.callAttr("get", "first_half"));
        String mode = str(res.callAttr("get", "mode"));
        float seconds = floatOr(res.callAttr("get", "seconds"), 0f);
        List<String> notes = stringList(res.callAttr("get", "notes"));

        PyObject capturePy = res.callAttr("get", "capture");
        if (capturePy != null && !isNone(capturePy)) {
            Capture capture = new Capture();
            capture.pke = orEmpty(str(capturePy.callAttr("get", "pke")));
            capture.pkr = orEmpty(str(capturePy.callAttr("get", "pkr")));
            capture.nonce = orEmpty(str(capturePy.callAttr("get", "e_nonce")));
            capture.hash1 = orEmpty(str(capturePy.callAttr("get", "e_hash1")));
            capture.hash2 = orEmpty(str(capturePy.callAttr("get", "e_hash2")));
            capture.authKey = orEmpty(str(capturePy.callAttr("get", "authkey")));
            capture.enrolleeMac = orEmpty(str(capturePy.callAttr("get", "enrollee_mac")));
            capture.notes = stringList(res.callAttr("get", "capture_notes"));
            out.capture = capture;
        }

        if (out.capture != null || pin != null || firstHalf != null) {
            Crack crack = new Crack();
            crack.ok = out.pinRecovered && pin != null;
            crack.pin = pin;
            crack.firstHalf = firstHalf;
            crack.mode = mode;
            crack.engine = orEmpty(str(res.callAttr("get", "engine")));
            crack.seconds = seconds;
            crack.notes = notes;
            out.crack = crack;
        }

        PyObject verifyPy = res.callAttr("get", "verify");
        if (verifyPy != null && !isNone(verifyPy)) {
            out.verify = parseVerify(verifyPy, pin == null ? "" : pin, ssid);
        } else {
            out.verify = new Verify();
            out.verify.pin = pin == null ? "" : pin;
            out.verify.ssid = ssid;
            out.verify.statusCode = out.statusCode;
            out.verify.detail = out.detail;
        }
        return out;
    }

    // ------------------------------------------------------------------- verify

    public Verify verify(String bssid, String ssid, int channel, String pin,
                         String channelSource, LogSink sink) {
        PyObject res = module().callAttr("verify", bssid, ssid, channel, pin, channelSource, callback(sink));
        Verify verify = parseVerify(res, pin, ssid);
        String err = str(res.callAttr("get", "error"));
        if (err != null && !verify.attempted) {
            throw new IllegalStateException(err);
        }
        if (verify.detail.isEmpty() && err != null) {
            verify.detail = err;
        }
        return verify;
    }

    // --------------------------------------------------------------- driver test

    public List<DriverStep> testDriver(int fd, int vid, int pid, String nativeLibDir,
                                       DriverOverride override) {
        PyObject res = module().callAttr("test_driver", fd, vid, pid, nativeLibDir, overrideMap(override, false));
        List<DriverStep> steps = new ArrayList<>();
        PyObject raw = res.callAttr("get", "steps");
        if (raw != null && !isNone(raw)) {
            for (PyObject step : raw.asList()) {
                steps.add(new DriverStep(
                        orEmpty(str(step.callAttr("get", "name"))),
                        bool(step.callAttr("get", "ok")),
                        orEmpty(str(step.callAttr("get", "detail")))
                ));
            }
        }
        return steps;
    }

    // ------------------------------------------------------------------ helpers

    private Map<String, Object> overrideMap(DriverOverride override, boolean includeMode) {
        if (override == null || !override.isManual()) {
            return null;
        }
        Map<String, Object> map = new HashMap<>();
        if (includeMode) {
            map.put("mode", override.mode.name());
        }
        if (override.chipset != null) {
            map.put("chipset", override.chipset);
        }
        if (override.vid != null) {
            map.put("vid", override.vid);
        }
        if (override.pid != null) {
            map.put("pid", override.pid);
        }
        if (override.firmwarePath != null && !override.firmwarePath.isEmpty()) {
            map.put("firmware_path", override.firmwarePath);
        }
        return map;
    }

    private Verify parseVerify(PyObject res, String fallbackPin, String fallbackSsid) {
        Verify v = new Verify();
        v.ok = bool(res.callAttr("get", "ok"));
        v.attempted = bool(res.callAttr("get", "attempted"));
        Boolean pinOk = boolOrNull(res.callAttr("get", "pin_ok"));
        v.pinOk = pinOk == null ? v.ok : pinOk;
        String pin = str(res.callAttr("get", "pin"));
        v.pin = pin == null ? fallbackPin : pin;
        v.psk = str(res.callAttr("get", "psk"));
        String ssid = str(res.callAttr("get", "ssid"));
        v.ssid = ssid == null ? fallbackSsid : ssid;
        v.detail = orEmpty(str(res.callAttr("get", "detail")));
        v.statusCode = orEmpty(str(res.callAttr("get", "status_code")));
        v.configError = intOrNull(res.callAttr("get", "config_error"));
        v.configErrorName = orEmpty(str(res.callAttr("get", "config_error_name")));
        String flow = str(res.callAttr("get", "flow"));
        v.flow = flow == null ? "same_session" : flow;
        v.reachedM1 = bool(res.callAttr("get", "reached_m1"));
        v.identityReqs = intOr(res.callAttr("get", "identity_reqs"), 0);
        v.eapolResends = intOr(res.callAttr("get", "eapol_resends"), 0);
        v.ackFailures = intOr(res.callAttr("get", "ack_failures"), 0);
        String stage = str(res.callAttr("get", "stage"));
        v.stage = stage == null ? "assoc" : stage;
        v.hadEncryptedSettings = bool(res.callAttr("get", "had_encrypted_settings"));
        v.decryptOk = boolOrNull(res.callAttr("get", "decrypt_ok"));
        v.m4Sent = bool(res.callAttr("get", "m4_sent"));
        v.assocCount = intOr(res.callAttr("get", "assoc_count"), 0);
        return v;
    }

    private static boolean isNone(PyObject object) {
        return object == null || "None".equals(object.toString());
    }

    private static String str(PyObject object) {
        if (object == null) {
            return null;
        }
        String value = object.toString();
        if (value.isEmpty() || "None".equals(value)) {
            return null;
        }
        return value;
    }

    private static String orEmpty(String value) {
        return value == null ? "" : value;
    }

    private static boolean bool(PyObject object) {
        Boolean value = boolOrNull(object);
        return value != null && value;
    }

    private static Boolean boolOrNull(PyObject object) {
        if (isNone(object)) {
            return null;
        }
        try {
            return object.toBoolean();
        } catch (Throwable t) {
            return null;
        }
    }

    private static int intOr(PyObject object, int fallback) {
        Integer value = intOrNull(object);
        return value == null ? fallback : value;
    }

    private static Integer intOrNull(PyObject object) {
        if (isNone(object)) {
            return null;
        }
        try {
            return object.toInt();
        } catch (Throwable t) {
            return null;
        }
    }

    private static float floatOr(PyObject object, float fallback) {
        if (isNone(object)) {
            return fallback;
        }
        try {
            return object.toFloat();
        } catch (Throwable t) {
            return fallback;
        }
    }

    private static List<String> stringList(PyObject object) {
        List<String> out = new ArrayList<>();
        if (isNone(object)) {
            return out;
        }
        for (PyObject item : object.asList()) {
            out.add(item.toString());
        }
        return out;
    }
}
