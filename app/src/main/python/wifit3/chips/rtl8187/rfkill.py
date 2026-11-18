"""RTL8187 RFKILL GPIO poll.

Port of ``rtl8187_is_radio_enabled`` (``rtl8187/rfkill.c``). The kernel registers this as
a polling rfkill at probe (``rtl8187_rfkill_init``) and the rfkill core then re-runs it
every ~1.3-1.8 s (``rtl8187_rfkill_poll``) — on the wire it is a fixed 3-op signature:
read GPIO0, clear the rfkill bit on GPIO0, read GPIO1 — so the acceptance gate dispatches
it as a periodic async producer interleaved with the bring-up + channel hops.

[SRC] ``driver_sources/rtl818x-source-v6.18/rtl8187/rfkill.c`` + ``rtl8187.h`` (the mask).
"""
from __future__ import annotations

import logging

from .constants import REG_GPIO0, REG_GPIO1
from .transport import RTL8187Transport

logger = logging.getLogger(__name__)


def is_radio_enabled(t: RTL8187Transport, mask: int) -> bool:
    """True iff the hardware RF switch is on; ``mask`` is priv->rfkill_mask, picked in probe."""
    gpio = t.read8(REG_GPIO0)
    t.write8(REG_GPIO0, gpio & ~mask & 0xFF)
    gpio = t.read8(REG_GPIO1)
    return bool(gpio & mask)


def radio_enabled_stable(t: RTL8187Transport, mask: int,
                         samples: int = 3) -> tuple[bool, list[tuple[int, int]]]:
    """Sample the RFKILL pin a few times: one 'on' reading is enough.

    The kernel polls this GPIO continuously, but this driver only reads it once
    during a cold probe. Several RTL8187 dongles have no physical switch at all:
    the pin floats or settles late, so that single read can report OFF even
    though the radio works. Re-reading filters that noise. A switch that is
    genuinely OFF stays OFF in every sample, so no real kill switch is bypassed.

    Returns ``(radio_on, [(gpio0, gpio1), ...])``; the raw values are kept for
    the bring-up error message so a real hardware failure can be diagnosed.
    """
    reads: list[tuple[int, int]] = []
    on_count = 0
    for _ in range(max(1, samples)):
        gpio0 = t.read8(REG_GPIO0)
        t.write8(REG_GPIO0, gpio0 & ~mask & 0xFF)
        gpio1 = t.read8(REG_GPIO1)
        reads.append((gpio0, gpio1))
        if gpio1 & mask:
            on_count += 1
    logger.debug("rtl8187 rfkill mask=0x%02x reads=%s on=%d", mask, reads, on_count)
    return on_count > 0, reads
