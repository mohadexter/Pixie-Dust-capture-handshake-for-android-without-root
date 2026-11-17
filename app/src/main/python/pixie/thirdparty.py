"""Locate the optional wifit3 source tree.

wifit3 ships lightweight Python ports of the Linux USB drivers (``chips/``) plus
a complete WSC codec (``dot11/wsc``).  Re-implementing either would be a huge
amount of radio work for no benefit, so the live path reuses them as a library.
They are GPL-2.0-only; this project is licensed accordingly (see LICENSE).

Nothing here imports wifit3 eagerly: ``find_spec`` is used so ``pixie doctor``
stays fast and does not trip over a missing pyusb.
"""

from __future__ import annotations

import importlib.util
import os
import sys

from . import util

# Files that must exist inside the wifit3 *package* directory when on disk.
_REQUIRED = (
    "dot11/wsc/messages.py",
    "dot11/wsc/crypto.py",
    "campaigns/auth_assoc.py",
    "campaigns/wps/pixie.py",
    "device/manager.py",
    "chips/driver.py",
)

# Submodules that must resolve via importlib.util.find_spec.
_REQUIRED_MODULES = (
    "wifit3.dot11.wsc.messages",
    "wifit3.dot11.wsc.crypto",
    "wifit3.campaigns.auth_assoc",
    "wifit3.campaigns.wps.pixie",
    "wifit3.device.manager",
    "wifit3.chips.driver",
)

INSTALL_HINT = (
    "the live path needs the wifit3 source (its USB driver layer).\n"
    "  in Termux:   bash install.sh --live\n"
    "  elsewhere:   pip install pyusb libusb-package platformdirs rich textual\n"
    "               git clone https://github.com/derv82/wifit3 && "
    "export WIFIT3_SRC=$PWD/wifit3/src\n"
    "  (offline cracking with 'pixie crack' / 'pixie pcap' does not need it)"
)


def _submodules_available() -> bool:
    """Check that all required wifit3 submodules can be resolved via find_spec.
    
    This works across all import mechanisms (standard filesystem, zipimporter,
    and Chaquopy's AssetFinder) and regardless of whether modules are source (.py)
    or bytecode (.pyc).
    """
    for mod_name in _REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(mod_name) is None:
                return False
        except (ImportError, ValueError, AttributeError):
            return False
    return True


def candidate_dirs() -> list:
    """Directories that may contain the ``wifit3`` package (highest priority first)."""
    dirs = []
    env = os.environ.get("WIFIT3_SRC", "").strip()
    if env:
        dirs.append(os.path.expanduser(env))
    dirs.append(os.path.expanduser(os.path.join("~", "wifit3", "src")))
    dirs.append(os.path.expanduser(os.path.join("~", "wifit3")))
    return dirs


def _package_dir(root: str) -> str:
    """``root`` may be the src dir or the repo root; return the package dir."""
    direct = os.path.join(root, "wifit3")
    if os.path.isdir(direct):
        return direct
    nested = os.path.join(root, "src", "wifit3")
    if os.path.isdir(nested):
        return nested
    return direct


def _looks_complete(package_dir: str) -> bool:
    """Verify package completeness on disk or via virtual package spec."""
    if os.path.isdir(package_dir):
        has_py = all(os.path.isfile(os.path.join(package_dir, name)) for name in _REQUIRED)
        if has_py:
            return True
        has_pyc = all(
            os.path.isfile(os.path.join(package_dir, name + "c"))
            or os.path.isfile(os.path.join(package_dir, name))
            for name in _REQUIRED
        )
        if has_pyc:
            return True
    return _submodules_available()


def find() -> str | None:
    """The src directory holding a complete wifit3 package, or None."""
    # 1. Check if wifit3 is already discoverable via importlib (e.g. bundled in Chaquopy app.imy or sys.path)
    try:
        spec = importlib.util.find_spec("wifit3")
    except (ImportError, ValueError, AttributeError):
        spec = None
    if spec is not None:
        if _submodules_available():
            if spec.submodule_search_locations:
                for location in spec.submodule_search_locations:
                    return os.path.dirname(location)
            return ""

    # 2. Check candidate filesystem locations (desktop, Termux, WIFIT3_SRC)
    for root in candidate_dirs():
        package_dir = _package_dir(root)
        if _looks_complete(package_dir):
            return os.path.dirname(package_dir)
    return None


def available() -> bool:
    return find() is not None


def ensure_importable() -> str:
    """Make ``import wifit3`` work and return the src dir that was used."""
    found = find()
    if found is None:
        if util.is_android():
            raise util.PixieError(
                "The bundled wifit3 driver layer was not found in this APK build. "
                "Ensure APK packaging includes the complete wifit3 Python assets."
            )
        raise util.PixieError(INSTALL_HINT)
    if found and found not in sys.path:
        sys.path.insert(0, found)
    return found


def version() -> str | None:
    """The wifit3 version string, read without importing driver/pyusb dependencies."""
    # 1. If already in sys.modules, read directly
    if "wifit3" in sys.modules:
        return getattr(sys.modules["wifit3"], "__version__", None)

    # 2. Try reading source text via pkgutil or filesystem if available
    try:
        import pkgutil
        data = pkgutil.get_data("wifit3", "__init__.py")
        if data:
            for line in data.decode("utf-8", "replace").splitlines():
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except Exception:
        pass

    src = find()
    if src is not None:
        try:
            init_file = os.path.join(src, "wifit3", "__init__.py")
            if os.path.isfile(init_file):
                with open(init_file, "r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.startswith("__version__"):
                            return line.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            pass

    # 3. For compiled bytecode archives (e.g. Chaquopy app.imy where only .pyc exists):
    # wifit3/__init__.py is a 5-line file with no imports or dependencies, only __version__.
    try:
        import importlib
        mod = importlib.import_module("wifit3")
        return getattr(mod, "__version__", None)
    except Exception:
        return None
