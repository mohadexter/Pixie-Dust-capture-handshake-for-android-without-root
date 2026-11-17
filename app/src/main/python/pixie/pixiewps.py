"""Thin, testable wrapper around the ``pixiewps`` binary.

pixiewps (https://github.com/wiire-a/pixiewps) is the program that actually
performs the offline PixieDust recovery.  This module only builds its
arguments, runs it, and turns its output into structured data.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from . import util

# Expected byte lengths of the WPS values we care about.
EXPECTED_BYTES = {
    "pke": 192,
    "pkr": 192,
    "e_nonce": 16,
    "r_nonce": 16,
    "e_hash1": 32,
    "e_hash2": 32,
    "authkey": 32,
    "bssid": 6,
}

FIELD_ORDER = [
    "pke", "pkr", "e_nonce", "r_nonce", "e_hash1", "e_hash2", "authkey", "bssid",
]

REQUIRED = ["pke", "e_hash1", "e_hash2", "e_nonce"]

# pixiewps flags, in the order they are documented.
FLAGS = {
    "pke": "-e",
    "pkr": "-r",
    "e_hash1": "-s",
    "e_hash2": "-z",
    "authkey": "-a",
    "e_nonce": "-n",
    "r_nonce": "-m",
    "bssid": "-b",
}


@dataclass
class Params:
    """The values pixiewps needs.  Hex strings without separators."""

    pke: str = ""
    pkr: str = ""
    e_nonce: str = ""
    r_nonce: str = ""
    e_hash1: str = ""
    e_hash2: str = ""
    authkey: str = ""
    bssid: str = ""

    mode: str = ""
    start: str = ""
    end: str = ""
    jobs: int = 0
    verbosity: int = 0
    force: bool = False
    m7_enc: str = ""
    m5_enc: str = ""

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_mapping(cls, data: dict) -> "Params":
        """Build from a dict (imported JSON, pcap extraction, argparse...)."""
        params = cls()
        for name in FIELD_ORDER + ["m7_enc", "m5_enc", "mode", "start", "end"]:
            value = data.get(name)
            if value:
                setattr(params, name, util.clean_hex(value) if name not in ("mode", "start", "end") else str(value))
        if data.get("jobs"):
            params.jobs = int(data["jobs"])
        if data.get("verbosity"):
            params.verbosity = int(data["verbosity"])
        params.force = bool(data.get("force"))
        return params

    @property
    def dh_small(self) -> bool:
        """True when the registrar used --dh-small (public key == 2)."""
        pkr = util.clean_hex(self.pkr)
        return bool(pkr) and pkr.lstrip("0") == "2" and len(pkr) == EXPECTED_BYTES["pkr"] * 2

    # -- validation -----------------------------------------------------------

    def normalize(self) -> list[str]:
        """Clean every field and return a list of human readable warnings."""
        warnings: list[str] = []
        for name in FIELD_ORDER + ["m7_enc", "m5_enc"]:
            raw = getattr(self, name)
            if not raw:
                continue
            clean = util.validate_hex(raw, name)
            expected = EXPECTED_BYTES.get(name)
            if expected and len(clean) // 2 != expected:
                warnings.append(
                    f"{name}: expected {expected} bytes, got {len(clean) // 2} "
                    "(pixiewps will reject it if it is really wrong)"
                )
            setattr(self, name, clean)
        return warnings

    def missing(self) -> list[str]:
        missing = [name for name in REQUIRED if not getattr(self, name)]
        if not self.pkr and not self.dh_small:
            missing.append("pkr")
        if not self.authkey and not self.dh_small:
            missing.append("authkey")
        if self.dh_small and not self.authkey:
            if not self.r_nonce:
                missing.append("r_nonce (needed to compute authkey with --dh-small)")
            if not self.bssid:
                missing.append("bssid (needed to compute authkey with --dh-small)")
        return missing

    # -- rendering ------------------------------------------------------------

    def to_argv(self) -> list[str]:
        argv: list[str] = []
        for name, flag in FLAGS.items():
            value = getattr(self, name)
            if value:
                argv += [flag, value]
        if self.mode:
            argv += ["--mode", str(self.mode)]
        if self.start:
            argv += ["--start", str(self.start)]
        if self.end:
            argv += ["--end", str(self.end)]
        if self.jobs:
            argv += ["-j", str(self.jobs)]
        if self.verbosity:
            argv += ["-v", str(self.verbosity)]
        if self.m7_enc:
            argv += ["-7", self.m7_enc]
        if self.m5_enc:
            argv += ["-5", self.m5_enc]
        if self.force:
            argv.append("-f")
        return argv

    def to_dict(self) -> dict:
        data = {}
        for name in FIELD_ORDER:
            value = getattr(self, name)
            if value:
                data[name] = util.clean_hex(value)
        for extra in ("mode", "start", "end", "m7_enc", "m5_enc"):
            value = getattr(self, extra)
            if value:
                data[extra] = util.clean_hex(value) if extra in ("m7_enc", "m5_enc") else value
        if self.jobs:
            data["jobs"] = self.jobs
        if self.force:
            data["force"] = True
        return data


@dataclass
class CrackResult:
    pin: str | None = None
    psk: str | None = None
    ssid: str | None = None
    returncode: int = -1
    output: str = ""
    vulnerable: bool | None = None
    modes: list[str] = field(default_factory=list)
    argv: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.pin)

    def to_dict(self) -> dict:
        return {
            "pin": self.pin,
            "psk": self.psk,
            "ssid": self.ssid,
            "success": self.success,
            "vulnerable": self.vulnerable,
            "modes": self.modes,
            "returncode": self.returncode,
        }


# ---------------------------------------------------------------- binary lookup


def find_binary(override: str | None = None) -> list[str]:
    """Return the argv prefix used to launch pixiewps.

    ``override`` may be a path or a full command line (useful for wrappers and
    tests).  The PIXIE_PIXIEWPS environment variable has the same effect.  A
    single path ending in ``.py`` is run with the current interpreter.
    """
    for value in (override, os.environ.get("PIXIE_PIXIEWPS")):
        if not value:
            continue
        parts = util.split_command(value)
        if len(parts) == 1 and parts[0].endswith(".py") and os.path.isfile(parts[0]):
            return [sys.executable, parts[0]]
        return parts
    path = util.which("pixiewps")
    if path:
        return [path]
    raise util.ToolMissing(
        "pixiewps",
        hint="run ./install.sh in Termux, or: pkg install clang make git && "
             "git clone https://github.com/wiire-a/pixiewps && cd pixiewps && make",
    )


def version(binary: str | None = None, timeout: int = 15) -> str | None:
    try:
        argv = find_binary(binary)
        rc, out = util.run(argv + ["-V"], timeout=timeout)
    except (util.PixieError, TimeoutError, OSError):
        return None
    if rc != 0 and not out.strip():
        return None
    text = " ".join(out.split())
    match = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text)
    return match.group(1) if match else (text or None)


# ------------------------------------------------------------------- parsing


_LABEL_RE = {
    "pin": re.compile(r"\bpin\b\s*[:=]\s*(.+)$", re.IGNORECASE),
    "psk": re.compile(r"\bpsk\b\s*[:=]\s*(.+)$", re.IGNORECASE),
    "ssid": re.compile(r"\bssid\b\s*[:=]\s*(.+)$", re.IGNORECASE),
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    if value[:1] in "'\"":
        value = value[1:]
    if value[-1:] in "'\"":
        value = value[:-1]
    return value.strip()


def parse_output(text: str) -> CrackResult:
    """Extract PIN / PSK / SSID and a vulnerability verdict from pixiewps text."""
    result = CrackResult(output=text)
    lowered = text.lower()

    for line in text.splitlines():
        stripped = line.strip()
        low = stripped.lower()

        if "not vulnerable" in low or "not likely vulnerable" in low:
            result.vulnerable = False
        elif "likely vulnerable" in low or low.startswith("[+]") and "vulnerable" in low:
            result.vulnerable = True
        if "mode" in low and any(ch.isdigit() for ch in low):
            if stripped not in result.modes:
                result.modes.append(stripped)

        if result.pin is None and "pin" in low and "not found" not in low:
            match = _LABEL_RE["pin"].search(stripped)
            if match:
                value = _unquote(match.group(1))
                if value.lower() == "<empty>":
                    result.pin = "<empty>"
                elif re.fullmatch(r"\d{8}", value):
                    result.pin = value

        if result.psk is None and "psk" in low and "not found" not in low:
            match = _LABEL_RE["psk"].search(stripped)
            if match:
                value = _unquote(match.group(1))
                if value:
                    result.psk = value

        if result.ssid is None and "ssid" in low:
            match = _LABEL_RE["ssid"].search(stripped)
            if match:
                value = _unquote(match.group(1))
                if value:
                    result.ssid = value

    if result.pin is None and ("pin not found" in lowered or "not found" in lowered):
        result.vulnerable = False if result.vulnerable is None else result.vulnerable
    return result


# ---------------------------------------------------------------------- run


def crack(params: Params, *, binary: str | None = None, timeout: int = 0,
          on_line=None, ui=None, echo: bool = True) -> CrackResult:
    """Run pixiewps for the given parameters and return a structured result."""
    missing = params.missing()
    if missing:
        raise util.PixieError(
            "missing value(s): " + ", ".join(missing) +
            "\n  tip: 'pixie wizard' walks you through them, "
            "'pixie pcap <file>' tries to read them from a capture"
        )

    argv = find_binary(binary) + params.to_argv()
    try:
        rc, out = util.run_streaming(
            argv, on_line=on_line, timeout=timeout or None, echo=echo, ui=ui
        )
    except ToolMissing:
        raise
    result = parse_output(out)
    result.returncode = rc
    result.argv = argv
    return result
