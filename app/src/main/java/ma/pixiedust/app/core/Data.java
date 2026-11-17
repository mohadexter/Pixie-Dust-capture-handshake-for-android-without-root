package ma.pixiedust.app.core;

import java.util.ArrayList;
import java.util.List;

/**
 * Plain data holders shared by the engine, the repository and the UI.
 * Fields are public on purpose: these are immutable-ish value objects, and
 * getters would only add noise across ~8 screens.
 */
public final class Data {

    private Data() {
    }

    public enum Stage {
        USB(1),
        CAPTURE(2),
        OFFLINE(3),
        VERIFY(4),
        PASSWORD(5),
        DONE(6),
        FAILED(7);

        public final int step;

        Stage(int step) {
            this.step = step;
        }
    }

    public enum DriverMode {
        AUTO,
        MANUAL
    }

    public static final class DriverOverride {
        public DriverMode mode = DriverMode.AUTO;
        public String chipset;
        public String firmwarePath;
        public Integer vid;
        public Integer pid;

        public boolean isManual() {
            return mode == DriverMode.MANUAL || chipset != null || vid != null || pid != null;
        }

        public DriverOverride copy() {
            DriverOverride o = new DriverOverride();
            o.mode = mode;
            o.chipset = chipset;
            o.firmwarePath = firmwarePath;
            o.vid = vid;
            o.pid = pid;
            return o;
        }
    }

    public static final class AccessPoint {
        public String bssid = "";
        public String ssid = "";
        public int channel = 1;
        public int rssi = -70;
        public String encryption = "WPA2";
        public boolean wps = true;
        public String wpsVersion = "1.0";
        public boolean locked;
        public String vendor = "";
        public String model = "";
        /** Unique client MACs seen in data frames during the scan (monitor RX). */
        public int clients;

        public boolean isHidden() {
            return ssid.trim().isEmpty();
        }

        /** A usable WPS target: it must advertise WPS, be on 2.4 GHz and have a name. */
        public boolean canAttack() {
            return wps && channel >= 1 && channel <= 14 && !ssid.trim().isEmpty();
        }

        public String displayName(String hiddenFallback) {
            return isHidden() ? hiddenFallback : ssid;
        }
    }

    public static final class ScanOutcome {
        public List<AccessPoint> aps = new ArrayList<>();
        public int rxFrames;
        public int rxBursts;
        public int beaconCount;
        public int callbackErrors;
        public List<Integer> channels = new ArrayList<>();
        public float elapsedS;
        public String diagnostic = "ok";
        public String detail = "";
    }

    /** One client station seen in monitor RX (airodump-ng style). */
    public static final class Client {
        public String mac = "";
        public int rssi = -100;
        /** Seconds since the last frame from this MAC. */
        public float ageS;
    }

    public static final class Capture {
        public String pke = "";
        public String pkr = "";
        public String nonce = "";
        public String hash1 = "";
        public String hash2 = "";
        public String authKey = "";
        public String enrolleeMac = "";
        public List<String> notes = new ArrayList<>();
    }

    public static final class Crack {
        public boolean ok;
        public String pin;
        public String firstHalf;
        public String mode;
        public String engine = "native";
        public float seconds;
        public List<String> notes = new ArrayList<>();
    }

    public static final class Verify {
        public boolean ok;
        public boolean attempted;
        public boolean pinOk;
        public String pin = "";
        public String psk;
        public String ssid;
        public String detail = "";
        public String statusCode = "";
        public Integer configError;
        public String configErrorName = "";
        public String flow = "same_session";
        public boolean reachedM1;
        public int identityReqs;
        public int eapolResends;
        public int ackFailures;
        public String stage = "assoc";
        public boolean hadEncryptedSettings;
        public Boolean decryptOk;
        public boolean m4Sent;
        public int assocCount;

        public boolean hasPsk() {
            return psk != null && !psk.trim().isEmpty();
        }
    }

    public static final class AutoOutcome {
        public boolean ok;
        public boolean pinRecovered;
        public Capture capture;
        public Crack crack;
        public Verify verify = new Verify();
        public String statusCode = "";
        public String flow = "none";
        public int assocCount;
        public String detail = "";
        public boolean engineError;
        public String error;
    }

    /** One captured WPA 4-way handshake, saved as a .pcap file. */
    public static final class Handshake {
        public boolean ok;
        /** True only when wifit3's crackability check found a real pair. */
        public boolean complete;
        /** Alias of {@link #complete}, explicit for the UI. */
        public boolean valid;
        public int validPairs;
        public String clientMac = "";
        public String pair = "";
        /** Where the app wrote it first (private cache). */
        public String path = "";
        /** Where the user finds it: Download/&lt;folder&gt;/&lt;name&gt;. */
        public String publicPath = "";
        /** Content URI when the capture was published through MediaStore or SAF. */
        public String publicUri = "";
        public int frames;
        public int eapolFrames;
        public List<Integer> messages = new ArrayList<>();
        public int clients;
        public float elapsedS;
        public int deauthSent;
        public int deauthAcked;
        public int deauthBursts;
        public List<String> notes = new ArrayList<>();
        public String error = "";

        public boolean hasFile() {
            return (publicPath != null && !publicPath.trim().isEmpty())
                    || (path != null && !path.trim().isEmpty());
        }

        /** What the UI shows: the public path when publishing worked. */
        public String displayPath() {
            if (publicPath != null && !publicPath.trim().isEmpty()) {
                return publicPath;
            }
            return path == null ? "" : path;
        }
    }

    public static final class DriverStep {        public final String name;
        public final boolean ok;
        public final String detail;

        public DriverStep(String name, boolean ok, String detail) {
            this.name = name;
            this.ok = ok;
            this.detail = detail == null ? "" : detail;
        }
    }

    public static final class UsbAdapter {
        public String deviceName = "";
        public String productName = "";
        public String serial = "";
        public int vid;
        public int pid;
        public boolean hasPermission;
        public String chipset = "?";
        public String driverModule = "auto";
        public boolean supported;

        public String vidPid() {
            return String.format("%04x:%04x", vid, pid);
        }
    }
}
