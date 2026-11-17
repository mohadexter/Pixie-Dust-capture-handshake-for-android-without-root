"""Firmware inspection and resolution for bundled and custom .bin files."""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Optional

# Expected firmware files per chip family
CHIP_FIRMWARE_INFO: Dict[str, Dict[str, Any]] = {
    "rt5370": {"filename": "rt5370_fw.bin", "dir": "rt5370"},
    "rt5372": {"filename": "rt5372_fw.bin", "dir": "rt5372"},
    "rt5572": {"filename": "rt5572.bin", "dir": "rt5572"},
    "rt3070": {"filename": "rt3070_fw.bin", "dir": "rt3070"},
    "rt2800usb": {"filename": "rt5572.bin", "dir": "rt2800usb"},
    "mt7601u": {"filename": "mt7601u.bin", "dir": "mt7601u"},
    "mt76x0u": {"filename": "mt7610u_linux-firmware.bin", "dir": "mt76x0u"},
    "mt76x2u": {"filename": "mt7662_rom_patch_body.bin", "dir": "mt76x2u"},
    "mt7921au": {"filename": "WIFI_RAM_CODE_MT7961_1.bin", "dir": "mt7921au"},
    "mt7925au": {"filename": "WIFI_RAM_CODE_MT7925_1_1.bin", "dir": "mt7925au"},
    "rtl8188eus": {"filename": "rtl8188eufw.bin", "dir": "rtl8188eus"},
    "rtl8188eus_dkms": {"filename": "rtl8188eufw.bin", "dir": "rtl8188eus_dkms"},
    "rtl8192fu": {"filename": "rtl8192fufw.bin", "dir": "rtl8192fu"},
    "rtl8812au": {"filename": "rtw8812a_fw.bin", "dir": "rtl8812au"},
    "rtl8812au_dkms": {"filename": "rtl8812au_fw.bin", "dir": "rtl8812au_dkms"},
    "rtl8814au_dkms": {"filename": "rtl8814au_fw.bin", "dir": "rtl8814au_dkms"},
    "rtl8821au": {"filename": "rtw8821a_fw.bin", "dir": "rtl8821au"},
    "rtl8821cu_dkms": {"filename": "rtl8821cu_fw_nic.bin", "dir": "rtl8821cu_dkms"},
    "rtl8822bu": {"filename": "rtw8822b_fw.bin", "dir": "rtl8822bu"},
    "rtl8822cu": {"filename": "rtl8822c_fw_nic.bin", "dir": "rtl8822cu"},
    "rtl8922au": {"filename": "rtw8922a_fw-4.bin", "dir": "rtl8922au"},
    "rtw88_8814au": {"filename": "rtw8814a_fw-linux_firmware.bin", "dir": "rtw88_8814au"},
    "ar9271": {"filename": "htc_9271.fw", "dir": "ar9271_v2"},
    "ar9271_v2": {"filename": "htc_9271.fw", "dir": "ar9271_v2"},
}

MAX_FIRMWARE_SIZE = 4 * 1024 * 1024  # 4 MB limit


def compute_sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def get_bundled_firmware_path(chipset: str) -> Optional[str]:
    info = CHIP_FIRMWARE_INFO.get(chipset.lower())
    if not info:
        return None
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chip_dir = os.path.join(base_dir, "wifit3", "chips", info["dir"], "assets")
    path = os.path.join(chip_dir, info["filename"])
    if os.path.exists(path):
        return path
    return None


def get_firmware_info(chipset: str, custom_path: Optional[str] = None) -> Dict[str, Any]:
    """Returns metadata about the active/expected firmware for a given chip."""
    chip = chipset.lower()
    expected = CHIP_FIRMWARE_INFO.get(chip, {}).get("filename", f"{chip}.bin")

    target_path = None
    source = "missing"
    if custom_path and os.path.exists(custom_path):
        target_path = custom_path
        source = "custom"
    else:
        bundled = get_bundled_firmware_path(chip)
        if bundled:
            target_path = bundled
            source = "bundled"

    if not target_path or not os.path.exists(target_path):
        return {
            "chipset": chip,
            "expected_file": expected,
            "source": "missing",
            "size": 0,
            "sha256": "",
            "valid": False,
            "error": "Firmware file not found",
        }

    try:
        size = os.path.getsize(target_path)
        with open(target_path, "rb") as f:
            data = f.read()
        sha = compute_sha256(data)
        valid = size <= MAX_FIRMWARE_SIZE
        err = None if valid else f"File size {size} exceeds max {MAX_FIRMWARE_SIZE} bytes"
        return {
            "chipset": chip,
            "expected_file": expected,
            "path": target_path,
            "source": source,
            "size": size,
            "sha256": sha,
            "valid": valid,
            "error": err,
        }
    except Exception as exc:
        return {
            "chipset": chip,
            "expected_file": expected,
            "source": source,
            "size": 0,
            "sha256": "",
            "valid": False,
            "error": str(exc),
        }
