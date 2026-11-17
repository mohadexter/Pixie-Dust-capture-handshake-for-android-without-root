package ma.pixiedust.app.usb;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbManager;
import android.os.Build;

import androidx.core.content.ContextCompat;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import ma.pixiedust.app.core.Data;

/**
 * OTG plumbing: device discovery, runtime permission and the single open
 * {@link UsbDeviceConnection} whose file descriptor the Python engine borrows.
 */
public final class UsbOtg {

    public static final String ACTION_USB_PERMISSION = "ma.pixiedust.app.USB_PERMISSION";

    public static final class Opened {
        public final UsbDeviceConnection connection;
        public final int fd;

        Opened(UsbDeviceConnection connection, int fd) {
            this.connection = connection;
            this.fd = fd;
        }
    }

    private final Context context;
    private final UsbManager manager;
    private final Object lock = new Object();

    private UsbDeviceConnection connection;
    private UsbDevice connectedDevice;
    private boolean registered;

    private volatile CountDownLatch permissionLatch;
    private volatile Runnable detachListener;

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context ctx, Intent intent) {
            String action = intent == null ? null : intent.getAction();
            if (action == null) {
                return;
            }
            if (ACTION_USB_PERMISSION.equals(action)) {
                UsbDevice device = getDevice(intent);
                boolean granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false);
                if (!granted && device != null) {
                    granted = hasPermission(device);
                }
                CountDownLatch latch = permissionLatch;
                if (latch != null) {
                    if (granted) {
                        latch.countDown();
                    } else {
                        latch.countDown();
                    }
                }
            } else if (UsbManager.ACTION_USB_DEVICE_DETACHED.equals(action)) {
                CountDownLatch latch = permissionLatch;
                if (latch != null) {
                    latch.countDown();
                }
                Runnable listener = detachListener;
                if (listener != null) {
                    listener.run();
                }
            }
        }
    };

    public UsbOtg(Context context) {
        this.context = context.getApplicationContext();
        this.manager = (UsbManager) this.context.getSystemService(Context.USB_SERVICE);
    }

    public void setDetachListener(Runnable listener) {
        this.detachListener = listener;
    }

    public void register() {
        if (registered || manager == null) {
            return;
        }
        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_USB_PERMISSION);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        ContextCompat.registerReceiver(context, receiver, filter, ContextCompat.RECEIVER_EXPORTED);
        registered = true;
    }

    public void unregister() {
        if (!registered) {
            return;
        }
        try {
            context.unregisterReceiver(receiver);
        } catch (IllegalArgumentException ignored) {
            // already gone
        }
        registered = false;
    }

    public UsbDevice findAttached() {
        if (manager == null) {
            return null;
        }
        HashMap<String, UsbDevice> devices;
        try {
            devices = manager.getDeviceList();
        } catch (Exception e) {
            return null;
        }
        UsbDevice fallback = null;
        for (Map.Entry<String, UsbDevice> entry : devices.entrySet()) {
            UsbDevice device = entry.getValue();
            if (Adapters.find(device.getVendorId(), device.getProductId()) != null) {
                return device;
            }
            if (fallback == null) {
                fallback = device;
            }
        }
        return fallback;
    }

    public boolean hasPermission(UsbDevice device) {
        try {
            return device != null && manager != null && manager.hasPermission(device);
        } catch (Exception e) {
            return false;
        }
    }

    /** Requests access and blocks the engine thread until the user answers (or 15 s pass). */
    public boolean awaitPermission(UsbDevice device, long timeoutMs) {
        if (device == null) {
            return false;
        }
        if (hasPermission(device)) {
            return true;
        }
        CountDownLatch latch = new CountDownLatch(1);
        permissionLatch = latch;
        try {
            requestPermission(device);
            latch.await(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            permissionLatch = null;
        }
        return hasPermission(device);
    }

    public void requestPermission(UsbDevice device) {
        if (device == null || manager == null) {
            return;
        }
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            flags |= PendingIntent.FLAG_MUTABLE;
        }
        Intent intent = new Intent(ACTION_USB_PERMISSION).setPackage(context.getPackageName());
        PendingIntent pending = PendingIntent.getBroadcast(context, 0, intent, flags);
        manager.requestPermission(device, pending);
    }

    public Data.UsbAdapter describe(UsbDevice device) {
        if (device == null) {
            return null;
        }
        Data.UsbAdapter out = new Data.UsbAdapter();
        out.vid = device.getVendorId();
        out.pid = device.getProductId();
        out.deviceName = device.getDeviceName();
        out.hasPermission = hasPermission(device);
        Adapters.Info info = Adapters.find(out.vid, out.pid);
        out.supported = info != null;
        if (info != null) {
            out.chipset = info.chipset;
            out.driverModule = info.chipset.toLowerCase();
            out.productName = info.name;
        } else {
            out.chipset = "?";
            out.driverModule = "auto";
            out.productName = safeProductName(device);
        }
        out.serial = safeSerial(device);
        return out;
    }

    private String safeProductName(UsbDevice device) {
        try {
            String name = device.getProductName();
            return name == null ? "" : name;
        } catch (Exception e) {
            return "";
        }
    }

    private String safeSerial(UsbDevice device) {
        try {
            String serial = device.getSerialNumber();
            return serial == null ? "" : serial;
        } catch (Exception e) {
            return "";
        }
    }

    public Opened open(UsbDevice device) {
        synchronized (lock) {
            close();
            if (device == null || manager == null || !hasPermission(device)) {
                return null;
            }
            UsbDeviceConnection conn;
            try {
                conn = manager.openDevice(device);
            } catch (Exception e) {
                return null;
            }
            if (conn == null) {
                return null;
            }
            connection = conn;
            connectedDevice = device;
            return new Opened(conn, conn.getFileDescriptor());
        }
    }

    public boolean hasConnection() {
        synchronized (lock) {
            return connection != null && connectedDevice != null;
        }
    }

    public boolean isConnectedTo(UsbDevice device) {
        synchronized (lock) {
            if (connection == null || connectedDevice == null || device == null) {
                return false;
            }
            return connectedDevice.getVendorId() == device.getVendorId()
                    && connectedDevice.getProductId() == device.getProductId()
                    && connectedDevice.getDeviceName().equals(device.getDeviceName());
        }
    }

    public void close() {
        synchronized (lock) {
            if (connection != null) {
                try {
                    connection.close();
                } catch (Exception ignored) {
                    // nothing useful to do
                }
            }
            connection = null;
            connectedDevice = null;
        }
    }

    private static UsbDevice getDevice(Intent intent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice.class);
        }
        //noinspection deprecation
        return intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
    }
}
