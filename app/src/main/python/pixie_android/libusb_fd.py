"""libusb file descriptor shim for Android (Kotlin passes open UsbDeviceConnection fd)."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import types
from typing import Any, Optional

logger = logging.getLogger("PIXIE_SCAN")

# libusb option constants (libusb.h)
LIBUSB_OPTION_NO_DEVICE_DISCOVERY = 2
_SHIM_NAME = "libusb_package"


class _WrappedHandle:
    """Stand-in for usb.backend.libusb1._DeviceHandle wrapping Android's open fd."""
    __slots__ = ("devid", "handle", "closed")

    def __init__(self, devid: Any, handle: Any):
        self.devid = devid
        self.handle = handle
        self.closed = False


class FdState:
    def __init__(self):
        self._lock = threading.RLock()
        self.ctx: Any = None
        self.handle: Any = None
        self.lib: Any = None
        self.backend: Any = None
        self.wrapped_dev: Any = None
        self.lib_path: Optional[str] = None
        self.fd: Optional[int] = None
        self.vid: Optional[int] = None
        self.pid: Optional[int] = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self.handle is not None and self.ctx is not None

    def close(self):
        with self._lock:
            wrapped_dev = self.wrapped_dev
            handle = self.handle
            ctx = self.ctx
            lib = self.lib
            backend = self.backend
            old_fd = self.fd

            self.wrapped_dev = None
            self.handle = None
            self.ctx = None
            self.backend = None
            self.fd = None
            self.vid = None
            self.pid = None

            if wrapped_dev is not None:
                try:
                    if hasattr(wrapped_dev, "finalize"):
                        wrapped_dev.finalize()
                except Exception as e:
                    logger.warning("wrapped_dev finalize error: %s", e)

            if handle is not None and lib is not None:
                try:
                    lib.libusb_close(handle)
                except Exception as e:
                    logger.warning("libusb_close error: %s", e)

            if ctx is not None and lib is not None:
                try:
                    lib.libusb_exit(ctx)
                except Exception as e:
                    logger.warning("libusb_exit error: %s", e)

            if backend is not None:
                try:
                    backend.ctx = None
                except Exception:
                    pass

            if old_fd is not None:
                logger.info("PIXIE_SCAN: libusb_fd closed cleanly (fd=%s)", old_fd)


STATE = FdState()


# The app ships libusb as jniLibs/arm64-v8a/libusb-1.0.so and
# jniLibs/armeabi-v7a/libusb-1.0.so, so it is installed under
# ApplicationInfo.nativeLibraryDir. The bare sonames are a fallback for builds that keep
# the libraries inside the APK instead of extracting them.
_LIB_NAMES = ("libusb-1.0.so", "libusb1.0.so")


def _libusb_candidates(native_lib_dir: Optional[str] = None):
    candidates = []
    if native_lib_dir:
        for name in _LIB_NAMES:
            candidates.append(os.path.join(native_lib_dir, name))
    candidates.extend(_LIB_NAMES)
    return candidates


def load_libusb(native_lib_dir: Optional[str] = None):
    candidates = _libusb_candidates(native_lib_dir)
    errors = []
    for path in candidates:
        if path.startswith("/") and not os.path.exists(path):
            errors.append(f"{path}: missing")
            continue
        try:
            lib = ctypes.CDLL(path)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        if not hasattr(lib, "libusb_wrap_sys_device"):
            errors.append(f"{path}: built without libusb_wrap_sys_device (needs libusb >= 1.0.22)")
            continue
        logger.info("PIXIE_SCAN: libusb loaded from %s", path)
        return lib, path

    detail = "; ".join(errors)
    raise RuntimeError(
        "Could not load libusb-1.0.so for this CPU architecture. Details: " + detail
    )


class _LibusbVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_uint16),
        ("minor", ctypes.c_uint16),
        ("micro", ctypes.c_uint16),
        ("nano", ctypes.c_uint16),
        ("rc", ctypes.c_char_p),
        ("describe", ctypes.c_char_p),
    ]


def probe(native_lib_dir: Optional[str] = None) -> dict:
    """Loads libusb and runs init/exit without an adapter.

    Used by the Drivers screen so a packaging problem is visible before a scan.
    """
    try:
        lib, path = load_libusb(native_lib_dir)
    except Exception as exc:  # noqa: BLE001 - the message is shown in the UI
        return {"ok": False, "lib": "", "version": "", "error": str(exc)}

    ctx = ctypes.c_void_p()
    try:
        # Must happen before libusb_init: Android without root cannot enumerate
        # /dev/bus/usb, and the default discovery makes libusb_init fail with
        # LIBUSB_ERROR_IO (-1).
        _set_no_device_discovery(lib)
        res = lib.libusb_init(ctypes.byref(ctx))
        if res != 0 or not ctx.value:
            return {"ok": False, "lib": path, "version": "", "error": f"libusb_init failed (code {res})"}

        version = ""
        try:
            lib.libusb_get_version.restype = ctypes.POINTER(_LibusbVersion)
            ver = lib.libusb_get_version()
            if ver:
                v = ver.contents
                version = f"{v.major}.{v.minor}.{v.micro}"
        except Exception:
            version = ""

        return {"ok": True, "lib": path, "version": version, "error": ""}
    finally:
        if ctx.value:
            try:
                lib.libusb_exit(ctx)
            except Exception:
                pass


def _set_no_device_discovery(lib: Any) -> None:
    """Disable libusb hotplug/sysfs enumeration on non-rooted Android."""
    try:
        lib.libusb_set_option.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.libusb_set_option.restype = ctypes.c_int
        rc = lib.libusb_set_option(None, LIBUSB_OPTION_NO_DEVICE_DISCOVERY)
        if rc != 0:
            logger.warning("PIXIE_SCAN: libusb_set_option returned %s", rc)
    except Exception as e:
        logger.warning("PIXIE_SCAN: libusb_set_option skipped: %s", e)


def _create_shared_libusb_backend(libusb1_mod: Any, lib: Any, ctx: Any) -> Any:
    """Create a pyusb _LibUSB backend reusing the single wrapped ctx (no second libusb_init)."""
    import usb.backend

    backend = libusb1_mod._LibUSB.__new__(libusb1_mod._LibUSB)
    usb.backend.IBackend.__init__(backend)
    backend.lib = lib
    backend.ctx = ctx
    # Prevent pyusb's weakref/GC finalizer from calling libusb_exit(ctx) concurrently with STATE.close().
    backend._finalize_called = True
    backend._finalize_object = lambda: None
    return backend


def install_fd_backend(fd: int, vid: int, pid: int, native_lib_dir: Optional[str] = None):
    """Initializes libusb with the open Android fd and configures pyusb to use it."""
    with STATE._lock:
        STATE.close()

        try:
            import usb.backend.libusb1 as libusb1
        except ImportError as exc:
            raise RuntimeError("pyusb is missing") from exc

        lib, lib_path = load_libusb(native_lib_dir)
        libusb1._setup_prototypes(lib)
        libusb1._lib = lib

        _set_no_device_discovery(lib)

        ctx = ctypes.c_void_p()
        res = lib.libusb_init(ctypes.byref(ctx))
        if res != 0 or not ctx.value:
            raise RuntimeError(f"libusb_init failed with code {res}")
        STATE.ctx = ctx
        STATE.lib = lib
        STATE.fd = fd
        STATE.vid = vid
        STATE.pid = pid
        STATE.lib_path = lib_path

        lib.libusb_wrap_sys_device.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
        ]
        lib.libusb_wrap_sys_device.restype = ctypes.c_int
        lib.libusb_get_device.argtypes = [ctypes.c_void_p]
        lib.libusb_get_device.restype = ctypes.c_void_p

        handle = ctypes.c_void_p()
        code = lib.libusb_wrap_sys_device(ctx, fd, ctypes.byref(handle))
        if code != 0 or not handle.value:
            STATE.close()
            raise RuntimeError(f"libusb_wrap_sys_device failed (code {code})")
        STATE.handle = handle

        device_ptr = lib.libusb_get_device(handle)
        if not device_ptr:
            STATE.close()
            raise RuntimeError("libusb_get_device returned NULL for the wrapped fd")

        backend = _create_shared_libusb_backend(libusb1, lib, ctx)
        libusb1._lib_object = backend

        wrapped_dev = libusb1._Device(device_ptr)
        STATE.wrapped_dev = wrapped_dev

        def _enumerate():
            yield wrapped_dev

        def _open(dev):
            return _WrappedHandle(getattr(dev, "devid", wrapped_dev.devid), handle)

        def _close_device(dev_handle):
            # STATE.close() owns closing STATE.handle exactly once AFTER RxReaderThread joins.
            if dev_handle is not None and hasattr(dev_handle, "closed"):
                dev_handle.closed = True

        def _is_kernel_driver_active(dev_handle, intf):
            return False

        def _detach_kernel_driver(dev_handle, intf):
            return None

        def _reset_device(dev_handle):
            # Avoid invalidating Android's UsbDeviceConnection fd on non-rooted devices.
            return None

        def _get_configuration(dev_handle):
            """Report the active configuration for the wrapped fd.

            libusb cannot read the configuration of a device wrapped from an Android
            file descriptor and returns 0, which makes pyusb raise the misleading
            "Configuration not set" on the first control/bulk transfer (MT7601U et al).
            Fall back to the value in the cached configuration descriptor.
            """
            try:
                cfg = ctypes.c_int()
                if lib.libusb_get_configuration(dev_handle.handle, ctypes.byref(cfg)) == 0:
                    if cfg.value:
                        return cfg.value
            except Exception:
                pass
            try:
                return backend.get_configuration_descriptor(wrapped_dev, 0).bConfigurationValue
            except Exception:
                return 1

        backend.enumerate_devices = _enumerate
        backend.open_device = _open
        backend.close_device = _close_device
        backend.is_kernel_driver_active = _is_kernel_driver_active
        backend.detach_kernel_driver = _detach_kernel_driver
        backend.get_configuration = _get_configuration
        backend.reset_device = _reset_device
        STATE.backend = backend

        try:
            desc = backend.get_device_descriptor(wrapped_dev)
            logger.info(
                "PIXIE_SCAN: libusb wrapped fd=%s lib=%s desc=%04x:%04x bus=%s addr=%s config=%s",
                fd,
                lib_path,
                getattr(desc, "idVendor", vid),
                getattr(desc, "idProduct", pid),
                getattr(desc, "bus", "?"),
                getattr(desc, "address", "?"),
                _get_configuration(_WrappedHandle(wrapped_dev.devid, handle)),
            )
        except Exception as desc_exc:
            logger.warning("PIXIE_SCAN: could not read wrapped device descriptor: %s", desc_exc)

        shim = ensure_libusb_package_shim()
        shim.get_libusb1_backend = lambda: backend
        shim.get_library_path = lambda: lib_path

        return backend


def ensure_libusb_package_shim():
    """Ensure libusb_package stub exists in sys.modules so driver imports don't fail."""
    shim = sys.modules.get(_SHIM_NAME)
    if shim is None:
        shim = types.ModuleType(_SHIM_NAME)
        shim.__pixie_shim__ = True
        shim.get_libusb1_backend = lambda: STATE.backend
        shim.get_library_path = lambda: getattr(STATE, "lib_path", None)
        sys.modules[_SHIM_NAME] = shim
    return shim


# Automatically register safe stub on import
ensure_libusb_package_shim()


def close_fd():
    """Tear down wrapped libusb handle and context safely (idempotent)."""
    STATE.close()
