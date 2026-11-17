package ma.pixiedust.app.core;

import androidx.annotation.StringRes;

import ma.pixiedust.app.R;

/**
 * A failure that is safe to show to the user. The technical text (libusb,
 * config_error numbers, raw stage names) is kept in {@link #detail} and shown
 * in a collapsed row — never mixed into the headline sentence.
 */
public final class PixieError {

    public enum Kind {
        USB_PERMISSION,
        NO_DEVICE,
        NO_DRIVER,
        DRIVER_MISMATCH,
        WRONG_INTERFACE,
        FIRMWARE,
        ZEROCD,
        LIBUSB,
        INTERFACE_CLAIM,
        DRIVER_INIT,
        ZERO_FRAMES,
        NO_BEACONS,
        SCAN_EMPTY,
        WPS_LOCKED,
        M1M3_TIMEOUT,
        ASSOC_FAILED,
        NO_M1,
        OFFLINE_CRACK,
        ENGINE,
        VERIFY_REJECTED,
        PIN_OK_NO_CREDENTIAL,
        M7_DECRYPT,
        VERIFY_TIMEOUT,
        USB_DETACHED,
        INTERNAL
    }

    public final Kind kind;
    public final String detail;
    public final int rxFrames;
    public final Integer configError;
    public final String configErrorName;
    public final String suggested;

    private PixieError(Kind kind, String detail, int rxFrames, Integer configError,
                       String configErrorName, String suggested) {
        this.kind = kind;
        this.detail = detail == null ? "" : detail;
        this.rxFrames = rxFrames;
        this.configError = configError;
        this.configErrorName = configErrorName == null ? "" : configErrorName;
        this.suggested = suggested;
    }

    public static PixieError of(Kind kind) {
        return new PixieError(kind, "", 0, null, "", null);
    }

    public static PixieError of(Kind kind, String detail) {
        return new PixieError(kind, detail, 0, null, "", null);
    }

    public static PixieError noBeacons(int rxFrames, String detail) {
        return new PixieError(Kind.NO_BEACONS, detail, rxFrames, null, "", null);
    }

    public static PixieError driverMismatch(String suggested) {
        return new PixieError(Kind.DRIVER_MISMATCH, "", 0, null, "", suggested);
    }

    public static PixieError verifyRejected(String detail, Integer configError, String name) {
        return new PixieError(Kind.VERIFY_REJECTED, detail, 0, configError, name, null);
    }

    @StringRes
    public int messageRes() {
        switch (kind) {
            case USB_PERMISSION:
                return R.string.err_usb_permission;
            case NO_DEVICE:
                return R.string.err_no_device;
            case NO_DRIVER:
                return R.string.err_no_driver;
            case DRIVER_MISMATCH:
                return R.string.err_driver_mismatch;
            case WRONG_INTERFACE:
                return R.string.err_wrong_interface;
            case FIRMWARE:
                return R.string.err_firmware;
            case ZEROCD:
                return R.string.err_zerocd;
            case LIBUSB:
                return R.string.err_libusb;
            case INTERFACE_CLAIM:
                return R.string.err_interface_claim;
            case DRIVER_INIT:
                return R.string.err_driver_init;
            case ZERO_FRAMES:
                return R.string.err_zero_frames;
            case NO_BEACONS:
                return R.string.err_no_beacons;
            case SCAN_EMPTY:
                return R.string.err_scan_empty;
            case WPS_LOCKED:
                return R.string.err_wps_locked;
            case M1M3_TIMEOUT:
                return R.string.err_m1m3_timeout;
            case ASSOC_FAILED:
                return R.string.err_assoc_failed;
            case NO_M1:
                return R.string.err_no_m1;
            case OFFLINE_CRACK:
                return R.string.err_offline_crack;
            case ENGINE:
                return R.string.err_engine;
            case VERIFY_REJECTED:
                return R.string.err_verify_rejected;
            case PIN_OK_NO_CREDENTIAL:
                return R.string.err_pin_ok_no_credential;
            case M7_DECRYPT:
                return R.string.err_m7_decrypt;
            case VERIFY_TIMEOUT:
                return R.string.err_verify_timeout;
            case USB_DETACHED:
                return R.string.err_usb_detached;
            case INTERNAL:
            default:
                return R.string.err_internal;
        }
    }

    /** Localised "details" line used for logs and the expandable row. */
    public String technicalDetail() {
        StringBuilder sb = new StringBuilder();
        if (!detail.isEmpty()) {
            sb.append(detail);
        }
        if (configError != null) {
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append("config_error=").append(configError);
            if (!configErrorName.isEmpty()) {
                sb.append(" (").append(configErrorName).append(')');
            }
        }
        if (rxFrames > 0) {
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append("rx_frames=").append(rxFrames);
        }
        if (suggested != null && !suggested.isEmpty()) {
            if (sb.length() > 0) {
                sb.append('\n');
            }
            sb.append("suggested=").append(suggested);
        }
        return sb.toString();
    }
}
