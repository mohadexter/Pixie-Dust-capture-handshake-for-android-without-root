"""pixie - a small PixieDust-only WPS auditor for Termux.

Only the PixieDust attack is implemented: no handshake cracking, no WEP, no
EvilTwin, no online PIN brute force.  Offline recovery works everywhere; the
live capture path uses a supported USB Wi-Fi adapter through wifit3's driver
layer (GPL-2.0).  See README.md for the legal notice.
"""

__version__ = "0.3.0"
__all__ = ["__version__"]
