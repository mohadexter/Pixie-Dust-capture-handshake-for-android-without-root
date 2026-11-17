"""Command line interface for pixie."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import sys

from . import (
    __version__, doctor, live, menu, pcap, pixiewps, termux_usb, thirdparty, util,
    wpsscan, wpscrack,
)
from .ui import UI

EPILOG = """\
examples:
  pixie                        # interactive menu (scan, pick a number)
  pixie menu
  pixie doctor
  pixie pcap capture.pcap
  pixie pcap capture.pcap --run
  pixie crack -e <pke> -r <pkr> -n <e-nonce> -s <e-hash1> -z <e-hash2> -a <authkey>
  pixie wizard
  pixie live usb
  pixie live scan
  pixie live scan --all
  pixie live attack AA:BB:CC:DD:EE:FF
  pixie hunt --iface wlan0mon
  pixie probe --iface wlan0mon AA:BB:CC:DD:EE:FF

Only networks you own or are explicitly allowed to audit.
"""


# --------------------------------------------------------------------- helpers


def _add_params(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("-e", "--pke", help="enrollee public key (hex, 192 bytes)")
    sub.add_argument("-r", "--pkr", help="registrar public key (hex, 192 bytes)")
    sub.add_argument("-n", "--e-nonce", help="enrollee nonce (hex, 16 bytes)")
    sub.add_argument("-m", "--r-nonce", help="registrar nonce (hex, 16 bytes)")
    sub.add_argument("-s", "--e-hash1", help="enrollee hash 1 (hex, 32 bytes)")
    sub.add_argument("-z", "--e-hash2", help="enrollee hash 2 (hex, 32 bytes)")
    sub.add_argument("-a", "--authkey", help="authentication session key (hex, 32 bytes)")
    sub.add_argument("-b", "--bssid", help="access point BSSID (AA:BB:CC:DD:EE:FF)")
    sub.add_argument("--mode", help="pixiewps --mode (e.g. 1, 2 or 3)")
    sub.add_argument("--start", help="pixiewps --start [mm/]yyyy (mode 3)")
    sub.add_argument("--end", help="pixiewps --end [mm/]yyyy (mode 3)")
    sub.add_argument("-f", "--force", action="store_true",
                     help="pixiewps -f: brute force the full range (mode 3)")
    sub.add_argument("-j", "--jobs", type=int, default=0,
                     help="pixiewps -j: number of threads")
    sub.add_argument("-7", "--m7-enc", dest="m7_enc",
                     help="encrypted settings from M7 (mode 3)")
    sub.add_argument("-5", "--m5-enc", dest="m5_enc",
                     help="encrypted settings from M5 (mode 3)")


def _add_runtime(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--pixiewps", dest="pixiewps_bin", metavar="CMD",
                     help="pixiewps binary or command line (default: find in PATH)")
    sub.add_argument("--timeout", type=int, default=0, metavar="SECS",
                     help="kill pixiewps after N seconds (0 = no limit)")
    sub.add_argument("-v", "--verbose", action="count", default=0,
                     help="increase pixiewps verbosity (-v, -vv)")
    sub.add_argument("--engine", choices=("auto", "native", "pixiewps"), default="auto",
                     help="recovery engine (auto prefers the native wifit3 one)")
    sub.add_argument("--modes", metavar="LIST",
                     help="native modes to try: null,static,ralink,rtl819x,ecos")
    sub.add_argument("--deep", action="store_true",
                     help="native engine: also try the slow RTL819x timestamp sweep")
    sub.add_argument("--json", action="store_true", help="machine readable output")
    sub.add_argument("--save", metavar="FILE", help="also write the result as JSON")


def _add_live_runtime(sub: argparse.ArgumentParser, *, attack: bool = False) -> None:
    sub.add_argument("--usb", metavar="PATH",
                     help="termux-usb device path (default: first device found)")
    sub.add_argument("-v", "--verbose", action="count", default=0,
                     help="more progress output")
    sub.add_argument("--json", action="store_true", help="machine readable output")
    if not attack:
        sub.add_argument("--timeout", type=int, default=0, metavar="SECS",
                         help="scan duration (0 = 25s)")
        return
    sub.add_argument("--ssid", help="target SSID (skips the lookup scan)")
    sub.add_argument("--channel", type=int, help="target channel (skips the lookup scan)")
    sub.add_argument("--timeout", type=int, default=0, metavar="SECS",
                     help="M1..M3 capture timeout (0 = 30s)")
    sub.add_argument("--scan-timeout", type=int, default=15, metavar="SECS",
                     help="lookup scan duration when --ssid/--channel are missing")
    sub.add_argument("--verify", action="store_true",
                     help="after recovery, send ONE real WPS attempt to prove the PIN")
    sub.add_argument("--pixiewps", dest="pixiewps_bin", metavar="CMD",
                     help="pixiewps binary (only used by the pixiewps engine)")
    sub.add_argument("--engine", choices=("auto", "native", "pixiewps"), default="auto",
                     help="offline recovery engine")
    sub.add_argument("--modes", metavar="LIST",
                     help="native modes to try: null,static,ralink,rtl819x,ecos")
    sub.add_argument("--deep", action="store_true",
                     help="native engine: also try the slow RTL819x timestamp sweep")
    sub.add_argument("--save", metavar="FILE", help="write the full result as JSON")



def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise util.PixieError(f"cannot read {path}: {exc}") from None
    except json.JSONDecodeError as exc:
        raise util.PixieError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise util.PixieError(f"{path} must contain a JSON object")
    return data


def _merge_params(args) -> pixiewps.Params:
    data = {}
    if getattr(args, "from_file", None):
        data.update(_load_json(args.from_file))
    for name in ("pke", "pkr", "e_nonce", "r_nonce", "e_hash1", "e_hash2",
                 "authkey", "bssid", "mode", "start", "end", "m7_enc", "m5_enc"):
        value = getattr(args, name, None)
        if value:
            data[name] = value
    params = pixiewps.Params.from_mapping(data)
    params.jobs = getattr(args, "jobs", 0) or params.jobs
    params.verbosity = getattr(args, "verbose", 0) or params.verbosity
    params.force = bool(getattr(args, "force", False)) or params.force
    return params


def _print_result(ui, result, params=None, bssid=None) -> None:
    ui.title("result")
    modes = list(getattr(result, "modes_tried", None) or getattr(result, "modes", None) or [])
    engine = getattr(result, "engine", None)
    if result.success:
        ui.ok("WPS PIN recovered")
        rows = [
            ("PIN", result.pin),
            ("password", result.psk or "(offline only gives the PIN - use --verify for the password)"),
            ("SSID", result.ssid or "-"),
        ]
        mode = getattr(result, "mode", None)
        if mode:
            rows.append(("mode", mode))
        if engine:
            rows.append(("engine", engine))
        ui.kv(rows)
    else:
        label = "not vulnerable" if result.vulnerable is False else "no PIN recovered"
        ui.bad(f"PixieDust failed: {label}")
        first_half = getattr(result, "first_half", None)
        if first_half:
            ui.warn(f"PixieDust proved the first PIN half: {first_half}xxxx")
            ui.info("the second half needs an online attempt (reaver/bully)")
        if result.vulnerable is None:
            ui.info("no clear verdict - try --deep, or another capture")

    seconds = getattr(result, "seconds", 0.0)
    if seconds:
        ui.info(f"offline search took {seconds:.2f}s")

    if modes:
        ui.title("modes tried")
        for line in modes[:12]:
            ui.bullet(str(line))

    for note in getattr(result, "notes", None) or []:
        ui.warn(note)

    shown_bssid = bssid or getattr(params, "bssid", None)
    if shown_bssid:
        ui.line()
        ui.info(f"target BSSID: {shown_bssid}")


def _print_capture(ui, capture) -> None:
    ui.title("capture")
    ui.kv([
        ("BSSID", capture.ap.bssid),
        ("SSID", capture.ap.ssid or "-"),
        ("channel", capture.ap.channel or "-"),
        ("PKE", util.shorten(capture.pke, 8) or "-"),
        ("E-Nonce", capture.e_nonce or "-"),
        ("E-Hash1", util.shorten(capture.e_hash1, 8) or "-"),
        ("E-Hash2", util.shorten(capture.e_hash2, 8) or "-"),
        ("AuthKey", util.shorten(capture.authkey, 8) or "-"),
    ])
    for note in capture.notes:
        ui.warn(note)


def _print_verify(ui, verify) -> None:
    ui.title("verification")
    if verify.ok:
        ui.ok(f"PIN {verify.pin} accepted by the AP")
        ui.kv([("password", verify.psk or "-"), ("SSID", verify.ssid or "-")])
        return
    ui.bad("the AP did not accept the PIN")
    if verify.detail:
        ui.kv([("detail", verify.detail)])
    if verify.config_error is not None:
        ui.info(f"WSC config error code: {verify.config_error}")


def _modes_for(args) -> list:
    return wpscrack.resolve_modes(getattr(args, "modes", None),
                                  getattr(args, "deep", False))


async def _in_thread(func, *a, **kw):
    """Run a blocking CPU-bound call without stalling the USB event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *a, **kw))


def _live_usb_info() -> dict:
    termux = termux_usb.is_termux()
    helper = util.which("termux-usb")
    try:
        import usb.core  # noqa: F401

        pyusb = True
    except ImportError:
        pyusb = False
    libusb = None
    libusb_present = None
    if termux:
        libusb = os.environ.get(termux_usb.LIBUSB_ENV) or termux_usb.DEFAULT_LIBUSB
        libusb_present = os.path.exists(libusb)
    is_root = util.is_root()
    info = {
        "platform": util.platform_name(),
        "termux": termux,
        "termux_usb": helper,
        "usb_paths": termux_usb.device_paths() if helper else [],
        "pyusb": pyusb,
        "libusb": libusb,
        "libusb_present": libusb_present,
        "wifit3": thirdparty.find(),
        "wifit3_version": thirdparty.version(),
        "adapters": [],
        "notes": [],
        # The live path never asks for root: on Termux Android opens the adapter
        # through termux-usb; on a desktop the user needs a udev rule instead.
        "rootless": True,
        "is_root": is_root,
        "privileges": "root" if is_root else "normal user",
    }
    if not termux:
        info["notes"].append(
            "not running in Termux: termux-usb is not needed, normal USB permissions apply")
    if termux and is_root:
        info["notes"].append(
            "running as root is not required (and not supported): run 'pixie live ...' "
            "as the normal Termux user so termux-usb can show the USB permission dialog")
    if not pyusb:
        info["notes"].append("pyusb is missing - run: pip install pyusb")
    if info["wifit3"] is None:
        info["notes"].append(thirdparty.INSTALL_HINT)

    # On Termux the shim only exists after Android hands us an fd, so only
    # enumerate the bus when there is one (i.e. inside a termux-usb re-exec).
    can_probe = pyusb and thirdparty.available() and (
        not termux or termux_usb.inherited_fd() is not None)
    if can_probe:
        try:
            if termux_usb.inherited_fd() is not None:
                termux_usb.install_shim()
            thirdparty.ensure_importable()
            from wifit3.device import manager

            info["adapters"] = [
                {
                    "description": dev.description,
                    "vid": f"{dev.vid:04x}",
                    "pid": f"{dev.pid:04x}",
                    "bus": dev.bus,
                    "address": dev.address,
                }
                for dev in manager.devices()
            ]
        except Exception as exc:  # pragma: no cover - environment dependent
            info["notes"].append(f"adapter probe failed: {exc}")
    return info



def _maybe_save(path: str, payload: dict, ui) -> None:
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        ui.info(f"result written to {path}")
    except OSError as exc:
        ui.warn(f"could not write {path}: {exc}")


def _binary_for_display(path):
    """pixiewps argv for --dry-run, even when pixiewps is not installed yet."""
    try:
        return pixiewps.find_binary(path)
    except util.ToolMissing:
        return ["pixiewps"]


# -------------------------------------------------------------------- commands


def cmd_doctor(args, ui) -> int:
    return doctor.render(ui, binary=args.pixiewps_bin)


def cmd_crack(args, ui) -> int:
    params = _merge_params(args)
    warnings = params.normalize()
    for warning in warnings:
        if args.json:
            print(f"warning: {warning}", file=sys.stderr)
        else:
            ui.warn(warning)
    modes = _modes_for(args)

    if args.dry_run:
        if args.engine in ("auto", "native") and wpscrack.native_available():
            ui.info("dry run: native engine (wifit3 recover_pin)")
            ui.info("modes: " + ", ".join(modes))
        else:
            argv = _binary_for_display(args.pixiewps_bin) + params.to_argv()
            ui.info("dry run, command would be:")
            ui.line("  " + " ".join(argv))
        return 0

    if not args.json:
        ui.title("PixieDust")
        ui.kv([
            ("PKE", util.shorten(params.pke, 8)),
            ("PKR", util.shorten(params.pkr, 8) or ("2 (--dh-small)" if params.dh_small else "-")),
            ("E-Nonce", params.e_nonce or "-"),
            ("R-Nonce", params.r_nonce or "-"),
            ("AuthKey", util.shorten(params.authkey, 8) or "(computed by pixiewps)"),
            ("BSSID", params.bssid or "-"),
            ("engine", args.engine),
        ])
        ui.hr()

    result = wpscrack.crack(
        params,
        engine=args.engine,
        modes=modes,
        binary=args.pixiewps_bin,
        timeout=args.timeout,
        ui=ui,
        echo=not args.json,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_result(ui, result, params)

    _maybe_save(args.save, {
        "input": params.to_dict(),
        "result": result.to_dict(),
        "version": __version__,
    }, ui)
    return 0 if result.success else 1


def cmd_wizard(args, ui) -> int:
    ui.banner()
    ui.info("Paste the WPS values. ':' '-' and spaces are ignored. Empty = unknown.")
    ui.info("reaver prints the AuthKey as 'Authentication session key' during an attack.")
    ui.line()

    prompts = [
        ("pke", "Enrollee public key (PKE, 192 bytes)", True),
        ("pkr", "Registrar public key (PKR, 192 bytes)", True),
        ("e_nonce", "Enrollee nonce (E-Nonce, 16 bytes)", True),
        ("r_nonce", "Registrar nonce (R-Nonce, 16 bytes)", False),
        ("e_hash1", "Enrollee hash 1 (E-Hash1, 32 bytes)", True),
        ("e_hash2", "Enrollee hash 2 (E-Hash2, 32 bytes)", True),
        ("authkey", "Authentication session key (32 bytes)", False),
    ]
    values = {}
    for name, label, required in prompts:
        marker = ui.paint("*", "red") if required else ui.paint("?", "grey")
        value = ""
        for attempt in range(3):
            try:
                raw = input(f"  {marker} {label}: ").strip()
            except EOFError:
                ui.line()
                ui.bad("input closed - aborting")
                return 2
            if not raw:
                if required:
                    ui.warn("required value, try again")
                    continue
                value = ""
                break
            try:
                value = util.validate_hex(raw, name)
                break
            except util.PixieError as exc:
                ui.warn(str(exc))
                value = ""
        values[name] = value

    params = pixiewps.Params.from_mapping(values)
    params.verbosity = args.verbose or 0
    params.normalize()
    modes = _modes_for(args)

    if args.dry_run:
        if args.engine in ("auto", "native") and wpscrack.native_available():
            ui.info("dry run: native engine (wifit3 recover_pin)")
            ui.info("modes: " + ", ".join(modes))
        else:
            argv = _binary_for_display(args.pixiewps_bin) + params.to_argv()
            ui.info("dry run, command would be:")
            ui.line("  " + " ".join(argv))
        return 0

    ui.hr()
    result = wpscrack.crack(params, engine=args.engine, modes=modes,
                            binary=args.pixiewps_bin, timeout=args.timeout,
                            ui=ui, echo=True)
    _print_result(ui, result, params)
    _maybe_save(args.save, {"input": params.to_dict(), "result": result.to_dict()}, ui)
    return 0 if result.success else 1


def cmd_pcap(args, ui) -> int:
    capture = pcap.read_capture(args.file)
    if args.json:
        print(json.dumps({
            "file": capture.path,
            "packets": capture.packets,
            "wps_frames": capture.wps_frames,
            "linktypes": capture.linktypes,
            "handshakes": [
                {
                    "bssid": h.bssid,
                    "pke": h.pke,
                    "pkr": h.pkr,
                    "e_nonce": h.e_nonce,
                    "r_nonce": h.r_nonce,
                    "e_hash1": h.e_hash1,
                    "e_hash2": h.e_hash2,
                    "messages": h.seen,
                    "notes": h.notes,
                    "ready": h.ready(),
                }
                for h in capture.handshakes
            ],
        }, indent=2))
        return 0 if capture.handshakes else 1

    ui.title("capture")
    ui.kv([
        ("file", capture.path),
        ("packets", capture.packets),
        ("WPS frames", capture.wps_frames),
        ("link type(s)", ", ".join(str(t) for t in capture.linktypes) or "-"),
    ])

    if not capture.handshakes:
        ui.warn("no WPS messages found in this capture")
        ui.info("the capture must contain plain 802.11 EAP-WSC frames "
                "(monitor mode, WPS attempt in progress)")
        return 1

    ui.title("handshakes")
    rows = []
    for index, handshake in enumerate(capture.handshakes):
        rows.append((
            index,
            handshake.bssid,
            ",".join(handshake.seen) or "-",
            "yes" if handshake.ready() else "no",
        ))
    ui.table(("#", "bssid", "messages", "ready"), rows)

    handshake = capture.handshakes[args.index] if args.index is not None else capture.best()
    if handshake is None:
        ui.bad(f"index out of range (0..{len(capture.handshakes) - 1})")
        return 2

    ui.title(f"details for {handshake.bssid}")
    ui.table(("field", "value", "state"), pcap.handshake_report(handshake))
    for note in handshake.notes:
        ui.warn(note)

    params = handshake.to_params()
    absent = handshake.missing()
    if absent:
        ui.warn("fields absent from the capture: " + ", ".join(absent))

    if args.run:
        lacking = params.missing()
        if lacking:
            ui.bad("cannot recover the PIN: missing " + ", ".join(lacking))
            ui.info("AuthKey is printed by reaver/bully as 'Authentication session key'")
            return 1
        ui.hr()
        result = wpscrack.crack(params, engine=args.engine, modes=_modes_for(args),
                                binary=args.pixiewps_bin, timeout=args.timeout,
                                ui=ui, echo=True)
        _print_result(ui, result, params)
        _maybe_save(args.save, {"input": params.to_dict(), "result": result.to_dict()}, ui)
        return 0 if result.success else 1

    # Show the exact next command.
    ui.title("next step")
    if handshake.dh_small:
        ui.info("this target used --dh-small, so pixiewps can derive AuthKey itself")
        ui.info(f"run: pixie pcap \"{args.file}\" --run")
    else:
        ui.warn("AuthKey is not stored in a capture.")
        ui.info("paste the 'Authentication session key' that reaver prints, then run:")
        ui.info(f"  pixie crack --from-file params.json -a <authkey>")
        ui.info(f"(use --save params.json to write the extracted values)")
    _maybe_save(args.save, {"input": params.to_dict(), "capture": args.file}, ui)
    return 0 if not absent else 1


def cmd_hunt(args, ui) -> int:
    if args.json:
        access_points, _ = wpsscan.hunt(args.iface, timeout=args.timeout, ui=None)
    else:
        access_points, _ = wpsscan.hunt(args.iface, timeout=args.timeout, ui=ui)
    if args.json:
        print(json.dumps([ap.to_dict() for ap in access_points], indent=2))
        return 0 if access_points else 1
    if not access_points:
        ui.warn("no WPS access point seen yet - try a longer --timeout")
        return 1
    ui.title("WPS access points")
    ui.table(
        ("bssid", "ch", "dbm", "wps", "lock", "essid"),
        [(ap.bssid, ap.channel, ap.rssi, ap.wps, ap.locked, ap.essid) for ap in access_points],
    )
    ui.line()
    ui.info("attack one with: pixie probe --iface <iface> <bssid>")
    return 0


def cmd_probe(args, ui) -> int:
    result = wpsscan.probe(
        iface=args.iface,
        bssid=args.bssid,
        tool=args.tool,
        timeout=args.timeout,
        ui=ui,
        extra_args=util.split_command(args.extra) if args.extra else None,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        ui.title("result")
        if result.success:
            ui.ok("WPS PIN recovered")
            ui.kv([("PIN", result.pin), ("PSK", result.psk or "-"), ("SSID", result.ssid or "-")])
        else:
            ui.bad("no PIN recovered with PixieDust")
        for note in result.notes:
            ui.warn(note)
        if result.log_path:
            ui.info(f"log: {result.log_path}")
    return 0 if result.success else 1


def cmd_version(args, ui) -> int:
    ui.line(f"pixie {__version__}")
    version = pixiewps.version(args.pixiewps_bin)
    ui.line(f"pixiewps {version or '(not found)'}")
    live_version = thirdparty.version()
    ui.line(f"wifit3 {live_version or '(not found - live path disabled)'}")
    ui.line(f"python {sys.version.split()[0]} on {util.platform_name()}")
    return 0


# --------------------------------------------------------------- live commands


def cmd_live_usb(args, ui) -> int:
    info = _live_usb_info()
    if args.json:
        print(json.dumps(info, indent=2))
        return 0 if info["termux_usb"] or not info["termux"] else 1

    ui.title("live USB")
    ui.kv([
        ("platform", info["platform"] + (" (Termux)" if info["termux"] else "")),
        ("privileges", f"{info['privileges']} (no root needed)"
            if info["rootless"] else info["privileges"]),
        ("termux-usb", info["termux_usb"] or "not found"),
        ("usb devices", ", ".join(info["usb_paths"]) or "none"),
        ("pyusb", "installed" if info["pyusb"] else "missing"),
        ("libusb", _libusb_label(info)),
        ("wifit3", f"{info['wifit3_version'] or '?'} - {info['wifit3']}" if info["wifit3"]
            else "not found"),
    ])
    if info["adapters"]:
        ui.title("supported adapters")
        ui.table(
            ("description", "vid:pid", "bus/addr"),
            [(a["description"], f"{a['vid']}:{a['pid']}",
              f"{a['bus']}/{a['address']}") for a in info["adapters"]],
        )
    elif info["termux"] and termux_usb.inherited_fd() is None:
        ui.info("run 'pixie live scan' to open the adapter and list it")
    for note in info["notes"]:
        ui.warn(note)
    return 0 if (info["pyusb"] or info["wifit3"]) else 1


def _libusb_label(info) -> str:
    if info["libusb"] is None:
        return "provided by the OS"
    state = "found" if info["libusb_present"] else "MISSING - pkg install libusb"
    return f"{info['libusb']} ({state})"


def cmd_live_scan(args, ui) -> int:
    access_points = asyncio.run(_live_scan(args, ui))
    if args.json:
        print(json.dumps([ap.to_dict() for ap in access_points], indent=2))
        return 0 if access_points else 1
    if not access_points:
        ui.warn("no access point seen")
        ui.info("try a longer --timeout, or move closer to the AP")
        return 1
    ui.title("access points (live)")
    menu.print_ap_table(ui, access_points)
    ui.line()
    if any(ap.wps for ap in access_points):
        ui.info("attack one with: pixie live attack <bssid>")
    ui.info("tip: 'pixie' opens the interactive menu (numbered list, auto-refresh)")
    return 0


async def _live_scan(args, ui):
    session = await live.open_session(ui)
    try:
        return await session.scan(
            timeout=args.timeout or live.SCAN_SECONDS,
            ui=ui,
            include_all=bool(getattr(args, "all_aps", False)),
        )
    finally:
        await session.close()


def cmd_menu(args, ui) -> int:
    if not _interactive():
        # Not a real terminal (pipe, script, or a termux-usb child without a
        # TTY): do not die silently - show one scan and how to continue.
        ui.info("stdin is not a terminal: showing one scan instead of the menu")
        args.json = False
        args.all_aps = True
        if not getattr(args, "timeout", 0):
            args.timeout = getattr(args, "scan_timeout", menu.SCAN_DEFAULT)
        return cmd_live_scan(args, ui)
    return menu.main(ui, args)


def _interactive() -> bool:
    """Only stdin matters: the menu can draw without a TTY on stdout."""
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def cmd_live_attack(args, ui) -> int:
    capture, outcome, verify = asyncio.run(_live_attack(args, ui))
    payload = {
        "version": __version__,
        "access_point": capture.ap.to_dict(),
        "capture": capture.to_dict()["capture"],
        "notes": list(capture.notes),
        "crack": outcome.to_dict(),
        "verify": verify.to_dict() if verify is not None else None,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_capture(ui, capture)
        _print_result(ui, outcome, bssid=capture.ap.bssid)
        if verify is not None:
            _print_verify(ui, verify)
        elif outcome.pin:
            ui.info("PIN not verified against the AP (add --verify to prove it and get the password)")
    _maybe_save(args.save, payload, ui)

    if not outcome.success:
        return 1
    if verify is not None and not verify.ok:
        return 1
    return 0


async def _live_attack(args, ui):
    timeout = float(args.timeout or live.CAPTURE_SECONDS)
    modes = _modes_for(args)
    session = await live.open_session(ui)
    try:
        ap = live.AccessPoint(
            bssid=args.bssid.lower(),
            ssid=args.ssid or "",
            channel=args.channel or 0,
        )
        if not ap.channel or not ap.ssid:
            if ui:
                ui.info(f"scanning {args.scan_timeout}s to find {ap.bssid} ...")
            found = await session.scan(timeout=float(args.scan_timeout), ui=None)
            match = next((item for item in found if item.bssid.lower() == ap.bssid), None)
            if match is not None:
                ap = live.AccessPoint(
                    bssid=match.bssid,
                    ssid=ap.ssid or match.ssid,
                    channel=ap.channel or match.channel,
                    rssi=match.rssi,
                    locked=match.locked,
                    version=match.version,
                    encryption=match.encryption,
                    vendor=match.vendor,
                    model=match.model,
                )
            elif not ap.channel or not ap.ssid:
                raise util.PixieError(
                    f"{ap.bssid}: not found among the WPS access points.\n"
                    "  pass --channel and --ssid if the AP is hidden or far away, "
                    "or raise --scan-timeout"
                )
        if ap.locked and ui:
            ui.warn("the AP advertises WPS locked; it will probably refuse the exchange")

        capture = await session.capture(ap, timeout=timeout, ui=ui)
        if ui:
            ui.info("M3 captured - running the offline PixieDust search ...")
        outcome = await _in_thread(
            wpscrack.crack,
            capture.values(),
            engine=args.engine,
            modes=modes,
            binary=args.pixiewps_bin,
            timeout=0,
            ui=ui,
            echo=False,
        )
        verify = None
        if args.verify:
            if outcome.pin:
                verify = await session.verify_pin(ap, outcome.pin, ui=ui)
            elif ui:
                ui.warn("no PIN recovered - nothing to verify")
        return capture, outcome, verify
    finally:
        await session.close()



# ----------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixie",
        description="PixieDust-only WPS auditor (offline recovery + optional attack).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-color", action="store_true", help="disable colours")
    parser.add_argument("--version", action="store_true", help="show version and exit")
    subparsers = parser.add_subparsers(dest="command")

    sub = subparsers.add_parser("doctor", help="check the environment")
    sub.add_argument("--pixiewps", dest="pixiewps_bin", metavar="CMD",
                     help="pixiewps binary or command line")
    sub.set_defaults(func=cmd_doctor)

    sub = subparsers.add_parser("crack", help="run pixiewps on known values")
    _add_params(sub)
    _add_runtime(sub)
    sub.add_argument("--from-file", metavar="FILE", help="read parameters from JSON")
    sub.add_argument("--dry-run", action="store_true", help="only show the command")
    sub.set_defaults(func=cmd_crack)

    sub = subparsers.add_parser("wizard", help="type the values interactively")
    _add_runtime(sub)
    sub.add_argument("--dry-run", action="store_true", help="only show the command")
    sub.set_defaults(func=cmd_wizard)

    sub = subparsers.add_parser("pcap", help="extract the values from a capture")
    sub.add_argument("file", help=".pcap or .pcapng file")
    sub.add_argument("-i", "--index", type=int, help="handshake index (default: best)")
    sub.add_argument("--run", action="store_true", help="run pixiewps when possible")
    _add_runtime(sub)
    sub.set_defaults(func=cmd_pcap)

    sub = subparsers.add_parser("hunt", help="scan for WPS access points (wash)")
    sub.add_argument("--iface", help="monitor-mode interface")
    sub.add_argument("--timeout", type=int, default=30, help="scan duration (s)")
    sub.add_argument("--json", action="store_true")
    sub.set_defaults(func=cmd_hunt)

    sub = subparsers.add_parser("probe", help="single PixieDust attempt (reaver/bully)")
    sub.add_argument("bssid", help="target BSSID")
    sub.add_argument("--iface", help="monitor-mode interface")
    sub.add_argument("--tool", choices=("reaver", "bully"), default="reaver")
    sub.add_argument("--timeout", type=int, default=300, help="stop after N seconds")
    sub.add_argument("--extra", help="extra arguments for reaver/bully")
    sub.add_argument("--json", action="store_true")
    sub.set_defaults(func=cmd_probe)

    sub = subparsers.add_parser("version", help="show versions")
    sub.add_argument("--pixiewps", dest="pixiewps_bin", metavar="CMD")
    sub.set_defaults(func=cmd_version)

    # -- live: rootless USB adapter path (Termux OTG or a desktop adapter) ----
    live_parser = subparsers.add_parser(
        "live", help="live PixieDust over a USB Wi-Fi adapter (no root)")
    live_sub = live_parser.add_subparsers(dest="live_command")

    sub = live_sub.add_parser("usb", help="show what termux-usb / wifit3 can see")
    sub.add_argument("--json", action="store_true")
    sub.set_defaults(func=cmd_live_usb)

    sub = live_sub.add_parser("scan", help="scan for access points (WPS highlighted)")
    _add_live_runtime(sub)
    sub.add_argument("--all", dest="all_aps", action="store_true",
                     help="show every access point, not only WPS ones")
    sub.set_defaults(func=cmd_live_scan)

    sub = live_sub.add_parser("attack", help="capture M1..M3, then crack offline")
    sub.add_argument("bssid", help="target BSSID (AA:BB:CC:DD:EE:FF)")
    _add_live_runtime(sub, attack=True)
    sub.set_defaults(func=cmd_live_attack)

    # -- beginner menu --------------------------------------------------------
    sub = subparsers.add_parser(
        "menu", help="interactive numbered menu (auto-refresh, PIN + password)")
    sub.add_argument("--usb", metavar="PATH",
                     help="termux-usb device path (default: first device found)")
    sub.add_argument("--refresh", type=float, default=menu.REFRESH_DEFAULT, metavar="SECS",
                     help="auto-refresh interval while waiting (0 = off)")
    sub.add_argument("--scan-timeout", type=float, default=menu.SCAN_DEFAULT,
                     metavar="SECS", help="duration of each scan")
    sub.add_argument("--timeout", type=float, default=0, metavar="SECS",
                     help="M1..M3 capture timeout (0 = 30s)")
    sub.add_argument("--engine", choices=("auto", "native", "pixiewps"), default="auto",
                     help="recovery engine (auto prefers the native wifit3 one)")
    sub.add_argument("--modes", metavar="LIST",
                     help="native modes: null,static,ralink,rtl819x,ecos")
    sub.add_argument("--deep", action="store_true",
                     help="also try the slow RTL819x timestamp sweep")
    sub.add_argument("--pixiewps", dest="pixiewps_bin", metavar="CMD",
                     help="pixiewps binary or command line")
    sub.set_defaults(func=cmd_menu)

    return parser


def main(argv=None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # termux-usb appends the inherited fd; strip it before argparse sees it.
    termux_usb.take_inherited_fd(raw)

    parser = build_parser()
    args = parser.parse_args(raw)
    ui = UI(color=False if args.no_color else None)

    if getattr(args, "version", False) or args.command == "version":
        args.command = "version"
        args.func = cmd_version
        if not hasattr(args, "pixiewps_bin"):
            args.pixiewps_bin = None

    if not getattr(args, "func", None):
        # `pixie` / `pixie --no-color` with no subcommand: always open the menu
        # (which explains itself when stdin is not a terminal).
        raw = [*raw, "menu"]
        args = parser.parse_args(raw)
        ui = UI(color=False if args.no_color else None)

    # On Termux the adapter is only reachable through termux-usb: re-exec once
    # so Android opens it and hands us the fd.  Inside the child this is a no-op.
    if args.command in ("live", "menu") and (
            args.command == "menu"
            or getattr(args, "live_command", None) in ("scan", "attack")):
        code = termux_usb.maybe_relaunch(raw, getattr(args, "usb", None), ui)
        if code is not None:
            return code

    if args.command in ("live", "menu") and termux_usb.is_termux() and util.is_root():
        ui.warn("you are root: on Termux run 'pixie live ...' as the normal user - "
                "termux-usb needs to show the Android USB permission dialog and root bypasses it")

    try:
        return args.func(args, ui)
    except util.PixieError as exc:
        ui.line()
        ui.bad(str(exc))
        return 2
    except KeyboardInterrupt:
        ui.line()
        ui.warn("interrupted")
        return 130
    except BrokenPipeError:
        return 0
