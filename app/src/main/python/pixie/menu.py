"""Beginner-friendly interactive menu for the live PixieDust path.

Everything here is stdlib only (no textual/rich requirement): a plain ANSI
dashboard with a numbered list, automatic re-scanning while it waits, and
one-character answers.  That keeps it usable on a phone keyboard in Termux.

The list shows *every* access point, not only WPS ones:

* green  -> WPS is enabled (PixieDust can run)
* red    -> no WPS (PixieDust cannot recover a PIN on it)

After a PIN is recovered the menu offers to prove it with one real WPS attempt,
which is the only way to obtain the actual Wi-Fi **password** (PSK).  There is
no offline shortcut: the PIN is not the passphrase.
"""

from __future__ import annotations

import asyncio
import functools
import os
import sys
import time

from . import live, util, wpscrack

WPS_ON_COLOR = "green"
WPS_OFF_COLOR = "red"

REFRESH_DEFAULT = 30.0
SCAN_DEFAULT = 20.0


# ------------------------------------------------------------------ formatting


def signal_label(rssi: int) -> str:
    """Very rough quality label for a dBm value."""
    if rssi >= -50:
        return "excellent"
    if rssi >= -60:
        return "good"
    if rssi >= -70:
        return "fair"
    return "weak"


def wps_label(ap) -> str:
    if not ap.wps:
        return "no"
    return ap.version or "yes"


def lock_label(ap) -> str:
    return "locked" if ap.locked else "open"


def color_for(ap) -> str:
    return WPS_ON_COLOR if ap.wps else WPS_OFF_COLOR


def ap_headers(numbered: bool = False) -> tuple:
    headers = ["bssid", "ch", "dbm", "security", "wps", "lock", "essid"]
    return tuple(["#"] + headers) if numbered else tuple(headers)


def ap_row(ap, index: int | None = None) -> list:
    row = [
        ap.bssid,
        str(ap.channel or "-"),
        str(ap.rssi),
        ap.encryption or "-",
        wps_label(ap),
        lock_label(ap),
        ap.ssid or "<hidden>",
    ]
    if index is not None:
        row.insert(0, str(index))
    return row


def print_ap_table(ui, access_points, numbered: bool = False, legend: bool = True) -> None:
    """Print the coloured access-point table (green = WPS, red = no WPS)."""
    headers = ap_headers(numbered)
    rows = [ap_row(ap, i if numbered else None) for i, ap in enumerate(access_points, 1)]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    pad = "  "
    head = pad + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    ui.line(ui.paint(head, "grey", bold=True))
    ui.line(ui.paint(pad + "  ".join("-" * width for width in widths), "grey"))
    for ap, row in zip(access_points, rows):
        line = pad + "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        ui.line(ui.paint(line, color_for(ap)))
    if legend and access_points:
        ui.line()
        ui.line("  " + ui.paint("green = WPS enabled", WPS_ON_COLOR)
                + "    " + ui.paint("red = no WPS", WPS_OFF_COLOR))


def details_rows(ap) -> list:
    return [
        ("SSID", ap.ssid or "<hidden>"),
        ("BSSID", ap.bssid),
        ("channel", ap.channel or "?"),
        ("signal", f"{ap.rssi} dBm ({signal_label(ap.rssi)})"),
        ("security", ap.encryption or "?"),
        ("WPS", "yes" if ap.wps else "no"),
        ("WPS version", ap.version or "-"),
        ("WPS locked", "yes" if ap.locked else "no"),
        ("vendor", ap.vendor or "-"),
        ("model", ap.model or "-"),
    ]


# --------------------------------------------------------------------- input


def clear_screen(ui) -> None:
    """Clear the terminal, but only when we really are on one."""
    try:
        interactive = sys.stdout.isatty()
    except Exception:
        interactive = False
    if interactive:
        ui.write("\033[2J\033[H")
    else:
        ui.line()


def _read_line_posix(ui, timeout: float | None) -> str | None:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buffer: list[str] = []
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        tty.setcbreak(fd)
        while True:
            if deadline is None:
                ready, _, _ = select.select([fd], [], [])
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                return None
            char = os.read(fd, 1).decode("utf-8", "ignore")
            if char in ("\r", "\n"):
                ui.write("\n")
                return "".join(buffer)
            if char in ("\x7f", "\x08"):
                if buffer:
                    buffer.pop()
                    ui.write("\b \b")
                continue
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\x04" and not buffer:
                return "q"
            if char.isprintable():
                buffer.append(char)
                ui.write(char)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_line_windows(ui, timeout: float | None) -> str | None:
    import msvcrt

    buffer: list[str] = []
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return None
        if not msvcrt.kbhit():
            time.sleep(0.08)
            continue
        char = msvcrt.getwch()
        if char in ("\r", "\n"):
            ui.write("\n")
            return "".join(buffer)
        if char in ("\x08", "\x7f"):
            if buffer:
                buffer.pop()
                ui.write("\b \b")
            continue
        if char == "\x03":
            raise KeyboardInterrupt
        if char in ("\x00", "\xe0"):  # arrow / function key: swallow the pair
            msvcrt.getwch()
            continue
        if char.isprintable():
            buffer.append(char)
            ui.write(char)


def read_line(ui, timeout: float | None = None) -> str | None:
    """Read one line, waiting at most ``timeout`` seconds (None = forever).

    Returns ``None`` on timeout.  On a non-interactive stdin it falls back to a
    plain blocking ``readline`` so tests and pipes still work.
    """
    try:
        interactive = sys.stdin.isatty()
    except Exception:
        interactive = False
    if not interactive:
        line = sys.stdin.readline()
        return line.rstrip("\r\n") if line else None
    try:
        if os.name == "nt":
            return _read_line_windows(ui, timeout)
        return _read_line_posix(ui, timeout)
    except (ImportError, OSError):
        # Some terminals (or a redirected stdin) refuse cbreak mode.
        line = sys.stdin.readline()
        return line.rstrip("\r\n") if line else None


def ask(ui, prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    ui.write(f"{prompt} {hint}: ")
    answer = (read_line(ui, None) or "").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "o", "oui", "نعم", "ن")


def pause(ui) -> None:
    ui.write("  Enter للرجوع ... ")
    read_line(ui, None)
    ui.line()


# ------------------------------------------------------------------- choosing


def parse_choice(text: str, count: int):
    """Turn a typed answer into an action.

    * ``quit``        -> the user wants to leave
    * ``refresh``     -> rescan (empty input counts as refresh)
    * ``out-of-range``-> a number that is not in the list
    * ``unknown``     -> anything else
    * an ``int``      -> 0-based index into the list
    """
    answer = (text or "").strip().lower()
    if answer in ("q", "quit", "exit", "خروج", "خ"):
        return "quit"
    if answer in ("r", "refresh", "تحديث", ""):
        return "refresh"
    if answer.isdigit():
        index = int(answer)
        if 1 <= index <= count:
            return index - 1
        return "out-of-range"
    return "unknown"


# ---------------------------------------------------------------------- flow


async def _scan(session, ui, timeout: float, first: bool = False) -> list:
    ui.info(("الجاري نقلب على الشبكات ... (green = WPS)" if first
             else "تحديث البحث ..."))
    return await session.scan(timeout=timeout, ui=None, include_all=True)


def _draw_dashboard(ui, aps, refresh: float, adapter: str) -> None:
    clear_screen(ui)
    ui.title("pixie — شبكات Wi-Fi")
    ui.line(f"  adapter: {adapter}   ({len(aps)} AP)")
    if aps:
        print_ap_table(ui, aps, numbered=True)
    else:
        ui.warn("ما لقيتش حتى شبكة فـ هاد البحث.")
        if refresh > 0:
            ui.info(f"غادي نعاود نقلب بوحدي كل {int(refresh)}s — ولا دير r دابا.")
        else:
            ui.info("دير r باش تعاود البحث.")
        ui.info("شيك: الكارت فـ OTG؟ الـ AP قريب؟ جرب --scan-timeout 30")
        ui.info("RT5370/AR9271 كيخدمو غير 2.4GHz (channels 1-13).")
    ui.line()
    ui.line("  " + ui.paint("green", WPS_ON_COLOR) + " = فيها WPS (PixieDust)   "
            + ui.paint("red", WPS_OFF_COLOR) + " = بلا WPS")
    if refresh > 0:
        ui.line(f"  البحث كيتحدث بوحدو كل {int(refresh)}s — ما خاصك تدير والو.")
    ui.line("  [رقم] هجوم على الشبكة   [r] تحديث   [q] خروج")


async def _crack(values, opts, modes, ui):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(
        wpscrack.crack,
        values,
        engine=opts.engine,
        modes=modes,
        binary=opts.pixiewps_bin,
        timeout=0,
        ui=ui,
        echo=False,
    ))


def _print_details(ui, ap) -> None:
    ui.title("تفاصيل الشبكة")
    ui.kv(details_rows(ap))


def _print_outcome(ui, capture, outcome, verify) -> None:
    ui.title("النتيجة")
    if not outcome.success or not outcome.pin:
        ui.bad("ما لقيتش PIN بهاد القيم.")
        if outcome.first_half:
            ui.info(f"النص اللول من الـ PIN: {outcome.first_half}")
        for note in outcome.notes:
            ui.warn(note)
        ui.info("جرب: pixie menu --deep (بطيء ولكن كيغطي RTL819x)")
        return

    ui.ok(f"WPS PIN: {outcome.pin}")
    ui.kv([
        ("SSID", capture.ap.ssid or "-"),
        ("BSSID", capture.ap.bssid),
        ("mode", outcome.mode or "-"),
        ("engine", outcome.engine),
        ("time", f"{outcome.seconds:.2f}s"),
    ])
    if verify is None:
        if outcome.psk:
            ui.title("password")
            ui.line("  " + ui.paint(outcome.psk, "green", bold=True))
            return
        ui.info("الـ password ما كيتجابش بلا تأكيد: خاص محاولة WPS حقيقية وحدة.")
        return
    if verify.ok:
        ui.ok("الـ PIN صحيح — الـ AP قبلو.")
        if verify.psk:
            ui.title("password")
            ui.line("  " + ui.paint(verify.psk, "green", bold=True))
            if verify.ssid:
                ui.line()
                ui.info(f"SSID: {verify.ssid}")
        else:
            ui.warn("الـ AP قبل الـ PIN ولكن ما عطاناش الـ PSK فهاد الرد.")
    else:
        ui.bad(f"الـ AP رفض الـ PIN ({verify.detail or 'بلا تفاصيل'})")


async def _handle(ui, session, ap, opts, modes) -> None:
    clear_screen(ui)
    _print_details(ui, ap)
    ui.line()

    if not ap.wps:
        ui.bad("هاد الشبكة ما فيهاش WPS — PixieDust ما يقدرش يخدم عليها.")
        ui.info("ختار شبكة خضراء من اللائحة.")
        pause(ui)
        return
    if not ap.channel:
        ui.bad("channel ما معروفش، ما نقدرش ندخلو. عاود البحث ولا استعمل live attack.")
        pause(ui)
        return
    if not ap.ssid:
        ui.bad("SSID مخبي. استعمل: pixie live attack <bssid> --ssid <SSID> --channel <ch>")
        pause(ui)
        return
    if ap.locked:
        ui.warn("هاد الـ AP كيقول WPS locked — غالبا غادي يرفض المحاولة.")

    if not ask(ui, "واش نبدا هجوم PixieDust على هاد الشبكة؟", default=True):
        return

    try:
        capture = await session.capture(ap, timeout=opts.capture_timeout, ui=ui)
    except util.PixieError as exc:
        ui.line()
        ui.bad(str(exc))
        pause(ui)
        return
    except Exception as exc:  # pragma: no cover - hardware dependent
        ui.bad(f"خطأ غير متوقع: {exc}")
        pause(ui)
        return

    ui.line()
    ui.info("M3 تنجح — الجاري البحث offline على الـ PIN ...")
    try:
        outcome = await _crack(capture.values(), opts, modes, ui)
    except util.PixieError as exc:
        ui.bad(str(exc))
        pause(ui)
        return

    verify = None
    if outcome.pin:
        ui.line()
        if ask(ui, "تأكيد الـ PIN وجلب password؟ (محاولة WPS حقيقية وحدة)", default=False):
            try:
                verify = await session.verify_pin(ap, outcome.pin, ui=ui)
            except util.PixieError as exc:
                ui.bad(str(exc))
            except Exception as exc:  # pragma: no cover - hardware dependent
                ui.bad(f"خطأ فـ التأكيد: {exc}")

    _print_outcome(ui, capture, outcome, verify)
    pause(ui)


async def run(ui, args) -> int:
    """Open one session and drive the menu until the user quits."""
    modes = wpscrack.resolve_modes(getattr(args, "modes", None),
                                  bool(getattr(args, "deep", False)))
    refresh = float(getattr(args, "refresh", REFRESH_DEFAULT) or 0)
    scan_timeout = float(getattr(args, "scan_timeout", 0) or SCAN_DEFAULT)
    opts = type("Options", (), {
        "engine": getattr(args, "engine", "auto"),
        "pixiewps_bin": getattr(args, "pixiewps_bin", None),
        "capture_timeout": float(getattr(args, "timeout", 0) or live.CAPTURE_SECONDS),
    })()

    ui.banner()
    session = await live.open_session(ui)
    try:
        ui.info(f"adapter: {session.description}")
        aps = await _scan(session, ui, scan_timeout, first=True)
        while True:
            _draw_dashboard(ui, aps, refresh, session.description)
            answer = read_line(ui, refresh if refresh > 0 else None)
            action = parse_choice(answer or "", len(aps)) if answer is not None else "refresh"

            if action == "quit":
                ui.line()
                ui.info("بسلامة!")
                return 0
            if action == "refresh":
                aps = await _scan(session, ui, scan_timeout)
                continue
            if action == "out-of-range":
                ui.warn("ما كاينش شبكة بهاد الرقم. عاود.")
                time.sleep(1.2)
                continue
            if action == "unknown":
                ui.warn("دخل رقم من اللائحة، ولا r للتحديث، ولا q للخروج.")
                time.sleep(1.2)
                continue

            ap = aps[action]
            await _handle(ui, session, ap, opts, modes)
            aps = await _scan(session, ui, scan_timeout)
    finally:
        await session.close()


def main(ui, args) -> int:
    """Synchronous entry point used by ``cli`` (wraps the async loop)."""
    try:
        return asyncio.run(run(ui, args))
    except KeyboardInterrupt:
        ui.line()
        ui.info("توقفت.")
        return 130
