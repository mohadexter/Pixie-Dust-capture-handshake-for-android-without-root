"""Terminal output helpers (stdlib only, degrades gracefully on dumb terminals)."""

from __future__ import annotations

import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
}

_UNICODE = {
    "ok": "\u2713",
    "bad": "\u2717",
    "warn": "!",
    "info": "\u203a",
    "arrow": "\u2192",
    "dot": "\u2022",
}

_ASCII = {
    "ok": "OK",
    "bad": "XX",
    "warn": "!!",
    "info": ">",
    "arrow": "->",
    "dot": "*",
}

BANNER = r"""
 _ __ (_)_  __(_) ___
| '_ \| \ \/ /| |/ _ \   PixieDust only
| |_) | |>  < | |  __/   offline WPS recovery
| .__/|_/_/\_\|_|\___|   for Termux / Linux
|_|
""".strip("\n")


class UI:
    """Small wrapper around stdout: colour, glyphs, tables."""

    def __init__(self, stream=None, color=None):
        self.stream = stream if stream is not None else sys.stdout
        self.color = self._detect_color() if color is None else bool(color)
        self.glyph = _UNICODE if self._detect_utf8() else _ASCII

    # -- capability detection -------------------------------------------------

    def _detect_color(self) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        if os.environ.get("TERM", "") == "dumb":
            return False
        try:
            return bool(self.stream.isatty())
        except Exception:
            return False

    def _detect_utf8(self) -> bool:
        enc = (getattr(self.stream, "encoding", None) or "").lower()
        if "utf" in enc:
            return True
        if enc in ("ascii", ""):
            # Termux and most modern terminals are UTF-8 even when python
            # cannot report it (e.g. redirected output on Windows).
            return os.environ.get("PYTHONIOENCODING", "").lower().startswith("utf")
        return False

    # -- low level ------------------------------------------------------------

    def paint(self, text: str, color: str | None = None, bold: bool = False) -> str:
        if not self.color:
            return text
        prefix = ""
        if bold:
            prefix += _BOLD
        if color and color in _CODES:
            prefix += _CODES[color]
        return prefix + text + _RESET if prefix else text

    def write(self, text: str = "") -> None:
        try:
            self.stream.write(text)
        except UnicodeEncodeError:
            enc = getattr(self.stream, "encoding", None) or "ascii"
            self.stream.write(text.encode(enc, "replace").decode(enc))

    def line(self, text: str = "") -> None:
        self.write(text + "\n")

    # -- semantic helpers -----------------------------------------------------

    def banner(self) -> None:
        for row in BANNER.splitlines():
            self.line(self.paint(row, "cyan", bold=True))
        self.line()

    def title(self, text: str) -> None:
        self.line()
        self.line(self.paint(text, "cyan", bold=True))
        self.line(self.paint("-" * max(10, len(text)), "grey"))

    def ok(self, text: str) -> None:
        self.line(self.paint(f"[{self.glyph['ok']}]", "green", bold=True) + " " + text)

    def bad(self, text: str) -> None:
        self.line(self.paint(f"[{self.glyph['bad']}]", "red", bold=True) + " " + text)

    def warn(self, text: str) -> None:
        self.line(self.paint(f"[{self.glyph['warn']}]", "yellow", bold=True) + " " + text)

    def info(self, text: str) -> None:
        self.line(self.paint(f"[{self.glyph['info']}]", "blue") + " " + text)

    def bullet(self, text: str) -> None:
        self.line("  " + self.paint(self.glyph["dot"], "grey") + " " + text)

    def kv(self, rows, indent: int = 2) -> None:
        """Print an aligned key/value block. ``rows`` is [(label, value), ...]."""
        width = max((len(str(label)) for label, _ in rows), default=0)
        for label, value in rows:
            pad = " " * indent
            self.line(f"{pad}{self.paint(str(label).ljust(width), 'grey')}  {value}")

    def table(self, headers, rows, indent: int = 2) -> None:
        widths = [len(str(h)) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))
        pad = " " * indent
        head = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
        self.line(pad + self.paint(head, "grey", bold=True))
        self.line(pad + self.paint("  ".join("-" * w for w in widths), "grey"))
        for row in rows:
            self.line(pad + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))

    def hr(self) -> None:
        try:
            width = min(os.get_terminal_size().columns, 78)
        except OSError:
            width = 60
        self.line(self.paint("-" * width, "grey"))
