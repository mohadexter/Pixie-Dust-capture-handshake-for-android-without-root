"""Rootless USB hand-off on Termux (``termux-usb`` + a libusb fd shim).

Android never lets an app open ``/dev/bus/usb/...`` directly.  ``termux-usb``
asks Android's ``UsbManager`` for permission, opens the adapter on our behalf,
and re-executes a command with the *inherited file descriptor* appended as its
last argument.  libusb can then adopt that fd with ``libusb_wrap_sys_device``
instead of enumerating and opening the device itself.

wifit3 (and every driver in it) does ``import libusb_package``.  On Termux there
is no usable bundled libusb, so we put a tiny module under that name in
``sys.modules``: it loads Termux's ``libusb-1.0.so``, turns device discovery off
(``LIBUSB_OPTION_NO_DEVICE_DISCOVERY``) and pretends the wrapped fd is the only
device on the bus.

Nothing in here imports wifit3; it only prepares the environment for it.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import types

from . import util

FD_ENV = "TERMUX_USB_FD"
PATH_ENV = "PIXIE_USB_PATH"
LIBUSB_ENV = "PIXIE_LIBUSB"
RELAUNCH_ENV = "PIXIE_RELAUNCHED"
DEFAULT_LIBUSB = "/data/data/com.termux/files/usr/lib/libusb-1.0.so"

# Sentinel we put in front of the fd when we re-exec through termux-usb, so a
# bare numeric argument can never be mistaken for the fd.
FD_FLAG = "--termux-fd"

# libusb option constants (libusb.h)
_LIBUSB_OPTION_NO_DEVICE_DISCOVERY = 2

_DEV_PATH = re.compile(r'"(/dev/[^"]+)"')


# --------------------------------------------------------------- availability


def is_termux() -> bool:
    """True when running inside Termux (Android + the Termux prefix)."""
    return util.is_termux()


def is_available() -> bool:
    """True when the ``termux-usb`` helper is installed."""
    return util.which("termux-usb") is not None


# ------------------------------------------------------- inherited descriptor


def inherited_fd() -> int | None:
    """The fd Android handed us, if any."""
    raw = os.environ.get(FD_ENV, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def take_inherited_fd(argv: list[str]) -> int | None:
    """Strip the ``--termux-fd <n>`` trailer from ``argv`` and record the fd.

    ``termux-usb -e`` appends the descriptor as the last argv item; we remove
    both the sentinel and the number before argparse ever sees them.
    """
    if FD_FLAG not in argv:
        return None
    argv.remove(FD_FLAG)
    fd = None
    if argv and argv[-1].lstrip("+-").isdigit():
        fd = int(argv.pop())
    if fd is not None:
        os.environ[FD_ENV] = str(fd)
    return fd


# -------------------------------------------------------------- device lookup


def device_paths() -> list:
    """Every USB device path ``termux-usb -l`` reports (may be empty)."""
    if not is_available():
        return []
    try:
        _rc, out = util.run([util.which("termux-usb") or "termux-usb", "-l"], timeout=20)
    except (util.PixieError, TimeoutError, OSError):
        return []
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, list):
        return [str(item) for item in data if str(item).startswith("/dev/")]
    return _DEV_PATH.findall(out)


def pick_device_path(explicit: str | None = None) -> str:
    """The ``/dev/bus/usb/...`` path to hand to ``termux-usb -r``."""
    for value in (explicit, os.environ.get(PATH_ENV)):
        if value:
            return value
    paths = device_paths()
    if not paths:
        raise util.PixieError(
            "termux-usb sees no USB device.\n"
            "  - is the adapter plugged in through a working OTG cable?\n"
            "  - does the phone's USB-C port support host mode?\n"
            "  - is Termux:API installed (pkg install termux-api) *and* its app installed?"
        )
    return paths[0]


# --------------------------------------------------------------- re-exec glue


def self_command(extra: list) -> list:
    """How to run this very tool again (for the termux-usb ``-e`` command)."""
    script = ""
    if sys.argv:
        script = os.path.abspath(sys.argv[0])
    if script.lower().endswith(".py") and os.path.isfile(script):
        return [sys.executable, script, *extra]
    # Console-script install: re-import the package by path.
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import sys; sys.path.insert(0, %r); "
        "from pixie.cli import main; sys.exit(main(sys.argv[1:]))"
    ) % (os.path.dirname(package_root),)
    return [sys.executable, "-c", code, *extra]


def relaunch(argv: list, usb_path: str | None = None, ui=None) -> int:
    """Run this command again through ``termux-usb`` so Android opens the adapter.

    Blocks until the child exits and returns its exit code.  The Android
    permission dialog is shown by ``termux-usb`` itself.
    """
    binary = util.which("termux-usb")
    if not binary:
        raise util.PixieError("termux-usb is not installed (pkg install termux-api)")
    path = pick_device_path(usb_path)
    inner = shlex.join(self_command([FD_FLAG, *argv]))
    if ui:
        ui.info("asking Android for USB permission (accept the dialog)...")
        ui.info(f"device: {path}")
    env = dict(os.environ)
    env[RELAUNCH_ENV] = "1"
    try:
        return subprocess.call([binary, "-r", "-e", inner, path], env=env)
    except OSError as exc:
        raise util.PixieError(f"could not run termux-usb: {exc}") from None


def maybe_relaunch(argv: list, usb_path: str | None = None, ui=None) -> int | None:
    """Re-exec through termux-usb when needed. ``None`` means "keep going".

    No-op when we already hold an fd or when termux-usb is unavailable (a Linux
    desktop with normal USB permissions does not need it).  The relaunch marker
    guarantees we never re-exec twice even if the fd never arrives.
    """
    if inherited_fd() is not None:
        return None
    if os.environ.get(RELAUNCH_ENV):
        if ui:
            ui.warn("termux-usb did not hand us a USB file descriptor - trying the direct path")
        return None
    if not is_available():
        return None
    return relaunch(argv, usb_path, ui)


# ------------------------------------------------------------- libusb_package


class _WrappedHandle:
    """Stand-in for ``usb.backend.libusb1._DeviceHandle``.

    Same two attributes pyusb's backend reads, but it never calls
    ``libusb_open`` because Android already opened the device for us.
    """

    __slots__ = ("devid", "handle")

    def __init__(self, devid, handle):
        self.devid = devid
        self.handle = handle


_SHIM_NAME = "libusb_package"


def shim_installed() -> bool:
    module = sys.modules.get(_SHIM_NAME)
    return bool(getattr(module, "__pixie_shim__", False))


def install_shim(force: bool = False) -> bool:
    """Install the ``libusb_package`` shim if we hold an Android fd.

    Returns True when a shim is active.  Outside Termux (or before
    ``termux-usb`` handed us anything) this is a no-op and returns False.
    """
    if not force and inherited_fd() is None:
        return False
    if shim_installed():
        return True

    backend = build_fd_backend(inherited_fd())
    module = types.ModuleType(_SHIM_NAME)
    module.__pixie_shim__ = True
    module.__doc__ = "pixie's Termux fd-backed stand-in for libusb_package"
    module.get_libusb1_backend = lambda: backend
    module.get_library_path = lambda: os.environ.get(LIBUSB_ENV) or DEFAULT_LIBUSB
    sys.modules[_SHIM_NAME] = module
    return True


def build_fd_backend(fd: int | None):
    """A pyusb libusb1 backend whose only device is the wrapped Android fd."""
    if fd is None:
        raise util.PixieError(
            "no Android USB file descriptor: run this through 'termux-usb' "
            "(pixie does that for you on Termux)"
        )
    try:
        import ctypes

        import usb.backend.libusb1 as libusb1
    except ImportError as exc:
        raise util.PixieError("pyusb is missing - run: pip install pyusb") from exc

    library = os.environ.get(LIBUSB_ENV) or DEFAULT_LIBUSB
    if not os.path.exists(library):
        raise util.PixieError(
            f"libusb not found at {library}\n  install it with: pkg install libusb"
        )

    lib = libusb1._load_library(find_library=lambda _name: library)
    if lib is None:
        raise util.PixieError(f"could not load {library}")
    libusb1._setup_prototypes(lib)

    # Tell libusb not to enumerate: the fd is the only device we may touch.
    lib.libusb_set_option.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_set_option.restype = ctypes.c_int
    lib.libusb_set_option(None, _LIBUSB_OPTION_NO_DEVICE_DISCOVERY)

    backend = libusb1._LibUSB(lib)
    # pyusb's other code paths (Device descriptors, bulk transfers) look these up.
    libusb1._lib = lib
    libusb1._lib_object = backend

    lib.libusb_wrap_sys_device.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
    ]
    lib.libusb_wrap_sys_device.restype = ctypes.c_int
    lib.libusb_get_device.argtypes = [ctypes.c_void_p]
    lib.libusb_get_device.restype = ctypes.c_void_p

    handle = ctypes.c_void_p()
    code = lib.libusb_wrap_sys_device(backend.ctx, fd, ctypes.byref(handle))
    if code != 0:
        raise util.PixieError(
            f"libusb_wrap_sys_device failed (libusb error {code}).\n"
            "  replug the adapter and accept the USB permission dialog again"
        )
    device_ptr = lib.libusb_get_device(handle)
    if not device_ptr:
        raise util.PixieError("libusb_get_device returned NULL for the wrapped fd")
    wrapped = libusb1._Device(device_ptr)

    def _enumerate():
        yield wrapped

    def _open(dev):
        if dev is wrapped:
            return _WrappedHandle(wrapped.devid, handle)
        return libusb1._DeviceHandle(dev)

    backend.enumerate_devices = _enumerate
    backend.open_device = _open
    return backend
