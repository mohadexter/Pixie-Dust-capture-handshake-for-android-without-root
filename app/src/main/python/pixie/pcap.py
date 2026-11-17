"""Extract WPS PixieDust parameters from a wireless capture (.pcap / .pcapng).

Only plain 802.11 frames carrying EAP-WSC (WPS) messages are inspected.  That
is exactly what a sniffer in monitor mode produces, and what reaver/bully
record while performing a PixieDust attempt.

No third-party dependency: the pcap, pcapng, radiotap, 802.11, LLC/SNAP,
EAPOL, EAP and WPS TLV parsers are all implemented here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import util
from .pixiewps import Params

# ------------------------------------------------------------------ constants

SNAP_EAPOL = b"\xaa\xaa\x03\x00\x00\x00\x88\x8e"
WPS_EAP_TYPE = 254
WFA_VENDOR_ID = b"\x00\x00\x00"
WSC_VENDOR_TYPE = b"\x00\x00\x00\x01"

LINKTYPE_ETHERNET = 1
LINKTYPE_IEEE802_11 = 105
LINKTYPE_RADIOTAP = 127
LINKTYPE_PPI = 192

WPS_ATTR_NAMES = {
    0x104A: "version",
    0x1044: "msg_type",
    0x1032: "public_key",
    0x101A: "nonce",
    0x1018: "e_hash1",
    0x1019: "e_hash2",
    0x101C: "r_hash1",
    0x101D: "r_hash2",
    0x1039: "encrypted_settings",
    0x1012: "auth_type",
    0x1011: "device_name",
    0x1021: "manufacturer",
    0x1023: "model_name",
    0x1024: "model_number",
    0x1053: "encr_type",
    0x1046: "key_wrap_auth",
    0x1015: "e_s1",
    0x1016: "e_s2",
    0x1017: "r_s1",
    0x1020: "r_s2",
}

MSG_NAMES = {
    0x04: "M1",
    0x05: "M2",
    0x07: "M3",
    0x08: "M4",
    0x09: "M5",
    0x0A: "M6",
    0x0B: "M7",
    0x0D: "M8",
}


class CaptureError(util.PixieError):
    """The file is not a capture we understand."""


# ---------------------------------------------------------------- data model


@dataclass
class Handshake:
    bssid: str = ""
    pke: str = ""
    pkr: str = ""
    e_nonce: str = ""
    r_nonce: str = ""
    e_hash1: str = ""
    e_hash2: str = ""
    seen: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def dh_small(self) -> bool:
        pkr = self.pkr
        return bool(pkr) and pkr.lstrip("0") == "2" and len(pkr) == 384

    def to_params(self) -> Params:
        return Params(
            pke=self.pke,
            pkr=self.pkr,
            e_nonce=self.e_nonce,
            r_nonce=self.r_nonce,
            e_hash1=self.e_hash1,
            e_hash2=self.e_hash2,
            bssid=self.bssid,
        )

    def missing(self) -> list:
        missing = []
        for name in ("pke", "pkr", "e_hash1", "e_hash2", "e_nonce"):
            if not getattr(self, name):
                missing.append(name)
        return missing

    def ready(self) -> bool:
        """True when pixiewps has everything it needs without an authkey.

        AuthKey is never stored in the capture: it is printed by reaver/bully
        while attacking.  The only exception is a registrar that used
        --dh-small, where pixiewps can derive it from the nonces and BSSID.
        """
        return not self.missing() and self.dh_small


@dataclass
class Capture:
    path: str
    packets: int = 0
    wps_frames: int = 0
    linktypes: list = field(default_factory=list)
    handshakes: list = field(default_factory=list)

    def best(self) -> Handshake | None:
        if not self.handshakes:
            return None
        return max(self.handshakes, key=lambda h: (not h.missing(), len(h.seen)))


# ---------------------------------------------------------------- pcap / pcapng


def _iter_pcap(data: bytes):
    if len(data) < 24:
        raise CaptureError("file is too small to be a pcap capture")
    magic = data[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian = "<"
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian = ">"
    elif magic == b"\x4d\x3c\xb2\xa1":  # nanosecond, little endian
        endian = "<"
    elif magic == b"\xa1\xb2\x3c\x4d":  # nanosecond, big endian
        endian = ">"
    else:
        raise CaptureError("not a pcap file (bad magic number)")

    linktype = struct.unpack(endian + "I", data[20:24])[0] & 0x0FFFFFFF
    offset = 24
    while offset + 16 <= len(data):
        incl_len = struct.unpack(endian + "I", data[offset + 8:offset + 12])[0]
        offset += 16
        if incl_len == 0:
            return
        chunk = data[offset:offset + incl_len]
        if len(chunk) < incl_len:
            if chunk:
                yield linktype, chunk
            return
        yield linktype, chunk
        offset += incl_len


def _iter_pcapng(data: bytes):
    offset = 0
    endian = None
    interfaces: list = []
    started = False
    while offset + 12 <= len(data):
        raw_type = data[offset:offset + 4]
        if raw_type == b"\x0a\x0d\x0d\x0a":  # Section Header Block
            bom = data[offset + 8:offset + 12]
            if bom == b"\x4d\x3c\x2b\x1a":
                endian = "<"
            elif bom == b"\x1a\x2b\x3c\x4d":
                endian = ">"
            else:
                raise CaptureError("pcapng: bad byte-order magic")
            started = True
            interfaces = []
            block_len = struct.unpack(endian + "I", data[offset + 4:offset + 8])[0]
            if block_len < 12:
                raise CaptureError("pcapng: corrupt section header")
            offset += block_len
            continue

        if not started:
            raise CaptureError("pcapng: missing section header block")

        block_type = struct.unpack(endian + "I", raw_type)[0]
        block_len = struct.unpack(endian + "I", data[offset + 4:offset + 8])[0]
        if block_len < 12 or offset + block_len > len(data):
            return
        body = data[offset + 8:offset + block_len - 4]

        if block_type == 1:  # Interface Description Block
            interfaces.append(struct.unpack(endian + "H", body[0:2])[0])
        elif block_type == 6:  # Enhanced Packet Block
            if len(body) >= 20:
                iface_id = struct.unpack(endian + "I", body[0:4])[0]
                cap_len = struct.unpack(endian + "I", body[12:16])[0]
                packet = body[20:20 + cap_len]
                linktype = interfaces[iface_id] if iface_id < len(interfaces) else LINKTYPE_RADIOTAP
                yield linktype, packet
        elif block_type == 3:  # Simple Packet Block
            if len(body) >= 4:
                packet = body[4:]
                linktype = interfaces[0] if interfaces else LINKTYPE_RADIOTAP
                yield linktype, packet.rstrip(b"\x00")

        offset += block_len


def iter_packets(data: bytes):
    if data[:4] == b"\x0a\x0d\x0d\x0a":
        yield from _iter_pcapng(data)
    else:
        yield from _iter_pcap(data)


# ---------------------------------------------------------------- link layer


def _strip_link_layer(linktype: int, packet: bytes) -> bytes:
    """Return the raw 802.11 frame, or b'' when the record is not 802.11."""
    if linktype == LINKTYPE_RADIOTAP:
        if len(packet) < 4:
            return b""
        radiotap_len = struct.unpack("<H", packet[2:4])[0]
        if 4 <= radiotap_len <= len(packet):
            return packet[radiotap_len:]
        return packet
    if linktype in (LINKTYPE_IEEE802_11, 0):
        return packet
    if linktype == LINKTYPE_PPI:
        if len(packet) < 8:
            return b""
        ppi_len = struct.unpack("<H", packet[2:4])[0]
        if 8 <= ppi_len <= len(packet):
            return packet[ppi_len:]
        return packet
    return b""


def _header_len(frame: bytes) -> int:
    if len(frame) < 24:
        return 24
    fc0, fc1 = frame[0], frame[1]
    subtype = (fc0 >> 4) & 0x0F
    to_ds = fc1 & 0x01
    from_ds = fc1 & 0x02
    length = 30 if (to_ds and from_ds) else 24
    if subtype & 0x08:  # QoS data
        length += 2
        if fc1 & 0x80:  # +HTC (order bit)
            length += 4
    return length


def _addresses(frame: bytes):
    if len(frame) < 22:
        return None
    return frame[4:10], frame[10:16], frame[16:22]


def _mac(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


# ---------------------------------------------------------------- EAP / WPS


def _find_eapol(frame: bytes, header_len: int) -> bytes | None:
    for start, stop in ((header_len, header_len + 80), (0, len(frame))):
        idx = frame.find(SNAP_EAPOL, start, min(stop, len(frame)))
        if idx >= 0:
            return frame[idx + len(SNAP_EAPOL):]
    return None


def _parse_eap_wsc(eapol: bytes) -> bytes | None:
    """EAPOL -> EAP -> expanded WSC.  Returns the WPS attribute blob."""
    if len(eapol) < 5:
        return None
    packet_type = eapol[1]
    if packet_type != 0:  # 0 == EAP packet
        return None
    eapol_len = struct.unpack(">H", eapol[2:4])[0]
    eap = eapol[4:4 + eapol_len]
    if len(eap) < 5:
        return None
    eap_len = struct.unpack(">H", eap[2:4])[0]
    eap_type = eap[4]
    # EAP Length counts the whole EAP packet, so the payload ends at eap_len.
    end = eap_len if 5 <= eap_len <= len(eap) else len(eap)
    body = eap[5:end]
    if eap_type != WPS_EAP_TYPE:
        return None
    if len(body) < 7:
        return None
    if body[0:3] != WFA_VENDOR_ID or body[3:7] != WSC_VENDOR_TYPE:
        return None
    return body[7:]


def parse_wps_attributes(blob: bytes) -> list:
    """Parse the big-endian TLV list of a WPS message."""
    attributes = []
    offset = 0
    while offset + 4 <= len(blob):
        attr_id, declared = struct.unpack(">HH", blob[offset:offset + 4])
        offset += 4
        value = blob[offset:offset + declared]
        attributes.append((attr_id, value, declared))
        offset += declared
        if offset > len(blob):
            break
    return attributes


def _hex(raw: bytes) -> str:
    return raw.hex()


def _full(values: dict, attr_id: int, expected: int) -> str:
    """Hex value of an attribute, but only when it is not truncated."""
    raw = values.get(attr_id)
    if raw is None or len(raw) != expected:
        return ""
    return _hex(raw)


def _frame_info(packet: bytes, linktype: int):
    frame = _strip_link_layer(linktype, packet)
    if len(frame) < 24:
        return None
    fc0 = frame[0]
    frame_type = (fc0 >> 2) & 0x03
    if frame_type != 2:  # only data frames carry EAPOL
        return None
    addrs = _addresses(frame)
    if not addrs:
        return None
    eapol = _find_eapol(frame, _header_len(frame))
    if not eapol:
        return None
    blob = _parse_eap_wsc(eapol)
    if not blob:
        return None
    attributes = parse_wps_attributes(blob)
    if not attributes:
        return None
    values = {attr_id: value for attr_id, value, _ in attributes}
    msg_type = values.get(0x1044)
    name = MSG_NAMES.get(msg_type[0], f"0x{msg_type[0]:02x}") if msg_type else "?"
    return {
        "addrs": addrs,
        "msg": name,
        "attributes": attributes,
        "values": values,
        "truncated": any(length > 0 and len(value) < length for _, value, length in attributes),
    }


# ---------------------------------------------------------------- extraction


def read_capture(path: str) -> Capture:
    with open(path, "rb") as handle:
        data = handle.read()
    if not data:
        raise CaptureError("the capture file is empty")

    capture = Capture(path=path)
    found: dict = {}

    for linktype, packet in iter_packets(data):
        capture.packets += 1
        if linktype not in capture.linktypes:
            capture.linktypes.append(linktype)
        info = _frame_info(packet, linktype)
        if not info:
            continue
        capture.wps_frames += 1

        a1, a2, a3 = info["addrs"]
        bssid = _mac(a3)
        handshake = found.get(bssid)
        if handshake is None:
            handshake = Handshake(bssid=bssid)
            found[bssid] = handshake

        msg = info["msg"]
        if msg not in handshake.seen:
            handshake.seen.append(msg)
        values = info["values"]
        notes = handshake.notes

        if msg == "M1":
            if not handshake.e_nonce:
                handshake.e_nonce = _full(values, 0x101A, 16)
            if not handshake.pke:
                handshake.pke = _full(values, 0x1032, 192)
        elif msg == "M2":
            if not handshake.r_nonce:
                handshake.r_nonce = _full(values, 0x101A, 16)
            if not handshake.pkr:
                handshake.pkr = _full(values, 0x1032, 192)
        elif msg == "M3":
            handshake.e_hash1 = _full(values, 0x1018, 32) or handshake.e_hash1
            handshake.e_hash2 = _full(values, 0x1019, 32) or handshake.e_hash2
            if info["truncated"] and not handshake.e_hash2:
                note = "M3 looks truncated (E-Hash2 missing) - capture may be incomplete"
                if note not in notes:
                    notes.append(note)

        if info["truncated"]:
            note = f"{msg} frame is truncated in the capture"
            if note not in notes:
                notes.append(note)

    capture.handshakes = list(found.values())
    for handshake in capture.handshakes:
        if handshake.dh_small:
            handshake.notes.append(
                "PKR == 2: the registrar used --dh-small, so pixiewps can "
                "compute AuthKey itself (no -a needed)"
            )
    return capture


def handshake_report(handshake: Handshake) -> list:
    """[(field, value, state)] for table rendering."""
    rows = []
    for name in ("pke", "pkr", "e_nonce", "r_nonce", "e_hash1", "e_hash2"):
        value = getattr(handshake, name)
        rows.append((name, util.shorten(value, 10) if value else "-",
                     "ok" if value else "missing"))
    return rows
