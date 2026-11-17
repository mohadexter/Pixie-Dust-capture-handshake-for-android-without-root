"""Small helpers shared by the rest of the package."""

from __future__ import annotations

import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading

HEX_SEPARATORS = re.compile(r"[\s:_-]")
HEX_ONLY = re.compile(r"^[0-9a-fA-F]*$")


class PixieError(Exception):
    """Anything that should be shown to the user as a clean error."""


class ToolMissing(PixieError):
    """A required external binary is not installed."""

    def __init__(self, name: str, hint: str = ""):
        self.name = name
        self.hint = hint
        msg = f"'{name}' was not found in PATH"
        if hint:
            msg += f"\n  hint: {hint}"
        super().__init__(msg)


def which(name: str) -> str | None:
    """shutil.which, but also looks in the Termux prefix and ~/.local/bin."""
    found = shutil.which(name)
    if found:
        return found
    candidates = []
    prefix = os.environ.get("PREFIX")
    if prefix:
        candidates.append(os.path.join(prefix, "bin", name))
    candidates.append(os.path.expanduser(os.path.join("~", ".local", "bin", name)))
    candidates.append(os.path.join(os.getcwd(), name))
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def clean_hex(value: str) -> str:
    """Strip ':' '-' ' ' separators and lowercase. Returns '' for empty input."""
    if value is None:
        return ""
    return HEX_SEPARATORS.sub("", str(value)).strip().lower()


def hex_len(value: str) -> int:
    return len(clean_hex(value)) // 2


def validate_hex(value: str, name: str, expected_bytes: int | None = None,
                 allow_empty: bool = False) -> str:
    """Normalise a hex string and check its shape. Returns the clean value."""
    clean = clean_hex(value)
    if not clean:
        if allow_empty:
            return ""
        raise PixieError(f"{name} is required")
    if not HEX_ONLY.match(clean):
        bad = sorted({c for c in clean if c not in "0123456789abcdef"})
        raise PixieError(f"{name} contains non-hex characters: {''.join(bad)}")
    if len(clean) % 2:
        raise PixieError(f"{name} has an odd number of hex digits ({len(clean)})")
    if expected_bytes is not None and len(clean) // 2 != expected_bytes:
        raise PixieError(
            f"{name} should be {expected_bytes} bytes ({expected_bytes * 2} hex chars), "
            f"got {len(clean) // 2} bytes"
        )
    return clean


def format_hex(value: str, group: int = 2) -> str:
    """Pretty-print long hex values as 'xx:xx:xx...' (or grouped as requested)."""
    clean = clean_hex(value)
    if not clean:
        return "-"
    step = group * 2
    chunks = [clean[i:i + step] for i in range(0, len(clean), step)]
    return ":".join(chunks)


def shorten(value: str, keep: int = 12) -> str:
    clean = clean_hex(value)
    if len(clean) <= keep * 2:
        return clean
    return f"{clean[:keep]}...{clean[-keep:]}"


def split_command(value: str) -> list[str]:
    """Turn a user supplied command string into argv (posix=False on Windows)."""
    if not value:
        return []
    return shlex.split(value, posix=(os.name != "nt"))


def run(argv, timeout=None, input_text=None, check=False, cwd=None):
    """Run a command, capture merged stdout+stderr as text."""
    try:
        proc = subprocess.run(
            argv,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            cwd=cwd,
            text=True,
            errors="replace",
        )
    except FileNotFoundError:
        raise ToolMissing(argv[0]) from None
    except subprocess.TimeoutExpired as exc:
        out = exc.output or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        raise TimeoutError(out) from None
    if check and proc.returncode != 0:
        raise PixieError(
            f"command failed ({proc.returncode}): {' '.join(argv)}\n{proc.stdout or ''}"
        )
    return proc.returncode, proc.stdout or ""


def run_streaming(argv, on_line, timeout=None, cwd=None, echo=True, ui=None):
    """Run a command, feeding every output line to ``on_line`` as it arrives.

    Returns (returncode, all_output).  Kills the process when ``timeout``
    seconds have elapsed.  Works on Windows and POSIX because it uses a
    reader thread instead of select().
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError:
        raise ToolMissing(argv[0]) from None

    lines: queue.Queue = queue.Queue()

    def reader():
        try:
            for raw in proc.stdout:
                lines.put(raw.rstrip("\r\n"))
        finally:
            lines.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    timer = None
    if timeout:
        def _kill():
            lines.put("__PIXIE_TIMEOUT__")
            try:
                proc.kill()
            except Exception:
                pass

        timer = threading.Timer(timeout, _kill)
        timer.daemon = True
        timer.start()

    buffer: list[str] = []
    while True:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None:
                # Give the reader a last chance to flush.
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    break
                if line is None:
                    break
            else:
                continue
        if line is None:
            break
        if line == "__PIXIE_TIMEOUT__":
            continue
        buffer.append(line)
        if echo:
            (ui.write(line + "\n") if ui else print(line))
        if on_line:
            on_line(line)

    if timer:
        timer.cancel()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    # Let the reader hit EOF, then close the pipe ourselves: Popen does not
    # close stdout for us and the leaked handle shows up as a ResourceWarning.
    thread.join(timeout=2)
    if proc.stdout is not None:
        proc.stdout.close()
    return proc.returncode, "\n".join(buffer)


def is_android() -> bool:
    if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ:
        return True
    return os.path.isdir("/system/app") and os.path.isdir("/data/data")


def is_termux() -> bool:
    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix or os.path.isdir("/data/data/com.termux/files/usr")


def geteuid() -> int:
    if hasattr(os, "geteuid"):
        return os.geteuid()
    return -1


def is_root() -> bool:
    """True on POSIX when running as root, True on Windows when elevated."""
    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return geteuid() == 0


def platform_name() -> str:
    if is_termux():
        return "termux"
    if is_android():
        return "android"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return sys.platform
