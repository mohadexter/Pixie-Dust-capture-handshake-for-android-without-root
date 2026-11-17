"""Environment self-check: tell the user exactly what is missing."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass

from . import pixiewps, termux_usb, thirdparty, util, wpsscan, wpscrack


@dataclass
class Check:
    name: str
    state: str  # "ok" | "warn" | "bad"
    detail: str = ""
    hint: str = ""


def _check_python() -> Check:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 8):
        detail = version
        if sys.version_info < (3, 11):
            detail += " (the live path needs 3.11+)"
        return Check("python", "ok", detail)
    return Check("python", "bad", version, "pixie needs Python 3.8 or newer")


def _check_platform() -> Check:
    name = util.platform_name()
    detail = f"{name}"
    if util.is_termux():
        detail += " (Termux)"
    elif name in ("linux", "macos"):
        detail += f" ({platform.machine()})"
    return Check("platform", "ok", detail)


def _check_pixiewps(binary: str | None) -> Check:
    native = wpscrack.native_available()
    try:
        found = pixiewps.find_binary(binary)
    except util.ToolMissing:
        if native:
            return Check(
                "pixiewps", "warn", "not found (native engine available)",
                "optional: wifit3's pure-Python engine cracks offline without it",
            )
        return Check(
            "pixiewps", "bad", "not found",
            "run ./install.sh, or: pkg install clang make git && "
            "git clone https://github.com/wiire-a/pixiewps && cd pixiewps && make",
        )
    version = pixiewps.version(binary)
    return Check("pixiewps", "ok", f"{version or '?'} - {' '.join(found)}")


def _check_wifit3() -> Check:
    source = thirdparty.find()
    if source is None:
        return Check("wifit3", "warn", "source not found", thirdparty.INSTALL_HINT)
    return Check("wifit3", "ok", f"{thirdparty.version() or '?'} - {source}")


def _check_pyusb() -> Check:
    try:
        import usb.core  # noqa: F401
    except ImportError:
        return Check("pyusb", "warn", "not installed",
                     "only needed for 'pixie live': pip install pyusb")
    return Check("pyusb", "ok", "installed")


def _check_libusb() -> Check:
    if not util.is_termux():
        return Check("libusb", "ok", "provided by the OS / pyusb")
    path = os.environ.get(termux_usb.LIBUSB_ENV) or termux_usb.DEFAULT_LIBUSB
    if os.path.exists(path):
        return Check("libusb", "ok", path)
    return Check("libusb", "bad", f"missing {path}", "pkg install libusb")


def _check_termux_usb() -> Check:
    if not (util.is_termux() or util.is_android()):
        return Check("termux-usb", "ok", "not needed on this platform")
    path = util.which("termux-usb")
    if not path:
        return Check(
            "termux-usb", "bad", "not found",
            "pkg install termux-api AND install the Termux:API app from F-Droid",
        )
    return Check("termux-usb", "ok", path)


def _check_usb_devices() -> Check:
    if not (util.is_termux() or util.is_android()):
        return Check("usb devices", "ok", "use 'pixie live usb' to probe")
    paths = termux_usb.device_paths()
    if paths:
        return Check("usb devices", "ok", f"{len(paths)} found: " + ", ".join(paths[:3]))
    return Check(
        "usb devices", "warn", "none reported by termux-usb",
        "plug the adapter through an OTG cable; the phone's port must support host mode",
    )


def _check_root() -> Check:
    if util.is_root():
        return Check("privileges", "ok", "elevated (root/admin)")
    if util.is_termux() or util.is_android():
        return Check(
            "privileges", "ok", "not root",
            "PixieDust (offline and 'pixie live') does not need root; only "
            "'pixie hunt'/'pixie probe' (reaver/bully) do",
        )
    return Check(
        "privileges", "warn", "not root",
        "'crack', 'pcap' and 'live' work as a normal user; 'hunt'/'probe' need sudo",
    )


def _check_interfaces() -> Check:
    try:
        interfaces = wpsscan.list_interfaces()
    except Exception as exc:  # pragma: no cover - defensive
        return Check("interfaces", "warn", f"could not list: {exc}")
    if not interfaces:
        return Check(
            "interfaces", "warn", "none detected",
            "only needed for 'hunt'/'probe'; 'pixie live' uses the USB adapter directly",
        )
    monitors = [i["name"] for i in interfaces if i["type"] == "monitor"]
    names = ", ".join(f"{i['name']}({i['type']})" for i in interfaces)
    if monitors:
        return Check("interfaces", "ok", f"{names} - monitor: {', '.join(monitors)}")
    return Check(
        "interfaces", "warn", names,
        "no monitor-mode interface yet (airmon-ng start wlan0, then --iface)",
    )


def _check_tool(name: str) -> Check:
    path = util.which(name)
    if not path:
        return Check(name, "warn", "not found", "only required for hunt/probe")
    return Check(name, "ok", path)


def collect(binary: str | None = None) -> list:
    checks = [
        _check_python(),
        _check_platform(),
        _check_pixiewps(binary),
        _check_wifit3(),
        _check_pyusb(),
        _check_libusb(),
        _check_termux_usb(),
        _check_usb_devices(),
        _check_root(),
    ]
    checks.append(_check_tool("iw"))
    checks.append(_check_interfaces())
    for tool in ("wash", "reaver", "bully"):
        checks.append(_check_tool(tool))
    return checks


def _live_ready(checks: list) -> bool:
    wanted = ("wifit3", "pyusb", "libusb", "termux-usb")
    found = {c.name: c for c in checks if c.name in wanted}
    if not all(name in found for name in wanted):
        return False
    return all(check.state == "ok" for check in found.values())


def render(ui, checks: list | None = None, binary: str | None = None) -> int:
    """Print the report. Returns the process exit code (0 = can crack offline)."""
    checks = checks if checks is not None else collect(binary)
    ui.title("environment")
    table = []
    for check in checks:
        table.append((check.name, check.detail or "-", check.state))
    ui.table(("component", "detail", "state"), table)

    failures = [c for c in checks if c.state == "bad"]
    warnings = [c for c in checks if c.state == "warn"]

    hints = [c for c in checks if c.hint and c.state != "ok"]
    if hints:
        ui.title("notes")
        for check in hints:
            ui.bullet(f"{check.name}: {check.hint}")

    ui.title("verdict")
    if not failures:
        ui.ok("offline PixieDust cracking is ready ('pixie crack' / 'pixie pcap').")
    else:
        for check in failures:
            ui.bad(f"{check.name}: {check.detail}")

    if _live_ready(checks):
        ui.ok("live PixieDust is ready ('pixie live scan' / 'pixie live attack').")
        if util.is_termux() or util.is_android():
            ui.info("rootless on Android: OTG + termux-usb, no 'su'/'sudo' involved.")
    else:
        ui.warn("the live path is not ready yet - see the wifit3/pyusb/libusb/termux-usb rows.")

    if warnings:
        ui.warn(f"{len(warnings)} warning(s) - the offline path may still work.")
    return 0 if not failures else 2
