# Pixie Dust: Auditing WPS and WPA Security from an Android Phone, Without Root

*A technical walkthrough of a native Android app that runs a complete USB Wi-Fi security audit on a phone, with no root, no `wpa_supplicant`, and no internet permission.*

---

## Why this project exists

Most Wi-Fi security tooling lives on a laptop. You install a Linux distribution, patch a driver to support monitor mode and packet injection, plug in a compatible USB adapter, and start `aircrack-ng`, `reaver`, or `hashcat`. It works, but it is heavy. It needs a second machine, a specific operating system, and a stack of driver patches that break with every kernel update.

Phones are the opposite: always with you, always charged, and — thanks to USB On-The-Go — perfectly capable of hosting a USB Wi-Fi adapter. What has been missing is the software layer that makes that hardware usable on unrooted Android.

**Pixie Dust** is an attempt to fill that gap. It is a single Android application, written in Java with an embedded Python engine, that brings a WPS audit and a WPA handshake capture to an ordinary phone. It does not require root, it does not touch `wpa_supplicant`, and it cannot send anything over the network, because it does not even request the `INTERNET` permission.

The project is open source under GPL-2.0:

**https://github.com/mohadexter/Pixie-Dust-for-android-without-root**

---

## What the app actually does

Pixie Dust has two jobs, and it keeps them strictly separate.

### 1. WPS PIN audit (the "Pixie Dust attack")

WPS — Wi-Fi Protected Setup — was designed to let a user join a network by typing an eight-digit PIN instead of a long passphrase. That convenience came at a cost. On a class of routers built around weak random number generators, the WPS exchange leaks enough information to recover the PIN offline.

The app performs **exactly one** attempt per run:

1. The adapter opens the target channel and brings up monitor receive.
2. The engine captures the WPS **M1, M2 and M3** messages.
3. The offline search reconstructs the router's nonces and derives a candidate PIN.
4. The candidate is validated in a single **M4–M7** exchange.
5. If the router accepts it, the same session asks for the passphrase, and the PSK comes back.

There is no retry loop. If the router rejects the attempt, or if it is not vulnerable at all, the app says so and stops. That single-attempt rule is deliberate: it is both the ethical boundary and the technical one, since modern routers lock WPS after a handful of failures. Burning the lockout budget on automated guesses is a good way to brick the feature on a router you own.

### 2. WPA 4-way handshake capture

The second job is the classic one. The app tunes to the target network, listens to the channel, and waits for a client to authenticate so it can record the four-way handshake. If no client reconnects on its own, a **bounded and targeted** deauthentication burst nudges the clients already observed on that BSSID into reconnecting.

The important part is what happens next. A capture is only reported as a success if the bundled validator finds a **crackable pair** — an actual M1/M2 pair from the same session. If no valid pair was found, no `.pcap` file is written at all. This avoids the most common frustration with handshake tools: a file appears, the user assumes it worked, and an hour later `hashcat` reports there was nothing usable in it.

---

## The architecture

The application is deliberately conservative about its dependencies. It uses plain Android Views, not Compose. The UI layer is Java and XML. The engine layer is Python, running in-process.

```
┌────────────────────────────────────────────────────────┐
│  Java UI  (Activities, ViewBinding, Material 3)        │
│  Scan · Details · Handshake · Attack · Result · …      │
└───────────────────────┬────────────────────────────────┘
                        │  Repo: one observable state
                        │  object, one listener, main thread
┌───────────────────────▼────────────────────────────────┐
│  Bridge.java  →  pixie_android.bridge (Python)         │
│  JSON contract, one engine thread ("pixie-engine")     │
└───────────────────────┬────────────────────────────────┘
                        │
┌───────────────────────▼────────────────────────────────┐
│  Python 3.11 (Chaquopy)                                │
│    pixie/        capture logic, PIN search, validation │
│    wifit3/       chipset drivers, firmware, monitor    │
│    pixie_android/  bridge, libusb_fd, callbacks        │
└───────────────────────┬────────────────────────────────┘
                        │  libusb 1.0.30
┌───────────────────────▼────────────────────────────────┐
│  USB OTG  →  RTL8812AU / MT7921AU / AR9271 / …         │
└────────────────────────────────────────────────────────┘
```

### One thread owns the radio

The single most important design decision is that **exactly one thread ever talks to the USB device**. The engine runs on a dedicated `pixie-engine` thread, and every operation — scan, capture, WPS attempt — is serialised through it. Two simultaneous USB transactions on the same adapter produce corrupted state, dropped frames, and drivers that stop responding. A strict queue removes that entire class of bug.

The UI never blocks on the engine. It reads a single observable state object (`Repo`) and redraws. Because the update callback is posted to the main thread, there is no locking in the UI code, and no chance of touching a View from a background thread.

### Getting libusb to work on Android without root

This is where most of the real work lives.

On a desktop, libusb opens a device by path. On Android, the USB device node under `/dev/bus/usb/` is not readable by an ordinary app. What an app *can* get is a **file descriptor** from the system, after the user grants permission through the standard OTG dialog.

The bridge therefore hands libusb an already-open descriptor instead of a device path, and lets libusb wrap it. The bundled `libusb_fd.py` module handles that handover, plus the platform quirks that come with it. The most notorious one is `libusb_get_configuration` failing with `Operation not permitted` on some chipset/phone combinations, which the module works around.

There is a second, less obvious problem: native libraries must exist as **real files on disk**, not inside the APK's zip. The Python binding loads libusb with `ctypes.CDLL(<nativeLibraryDir>/libusb-1.0.so)`, so the build is configured with `useLegacyPackaging = true` to force extraction at install time. Without that setting the app installs fine and then fails at the first USB call.

The Python packages that carry firmware blobs are likewise extracted rather than imported from the archive, because the drivers read them as files.

### Supported hardware

The driver stack covers a wide range of USB adapters — Ralink/MediaTek RT series, MT7601U through MT7925U (Wi-Fi 7), Atheros AR9271, and a broad set of Realtek parts including the popular RTL8812AU and RTL8814AU. The app ships an adapter screen that identifies the connected dongle by VID/PID and reports which chipset it matched, so a user is never left guessing why their adapter is not recognised.

Only ARM is shipped — `arm64-v8a` and `armeabi-v7a` — because the firmware blobs and the driver are architecture-specific and because x86 has no OTG radio to talk to anyway.

---

## The interface

The app is designed to be usable by someone who has never run a Wi-Fi audit before, without hiding what it is doing.

- **Scan network** lists nearby access points, strongest signal first, with the manufacturer and, where it is known, the router model. Manufacturer data is cached on-device, so a later scan that misses the WPS information element still shows the same router instead of a blank row.
- Tapping a network opens a compact sheet with the technical facts — BSSID, channel, encryption, WPS version, client count — and exactly two actions, presented as two equal cards: **Capture WPA handshake** and **PixieDust attack**. Each card is disabled and dimmed when the network cannot support it, so an impossible action is visible but obviously unavailable, rather than silently missing.
- The **capture screen** walks through the five stages (adapter, monitor, handshake, validation, save) with a live stepper, a plain-language explanation of the current stage, and one button that toggles between *Start capture handshake* and *Stop capture*.
- When a capture succeeds, a small frame appears over the screen with a short vibration: the success, the file path in a heavier monospace line, and a button to **open the file** in whatever viewer handles pcaps, plus a copy action. When a capture fails or the user stops it, the banner switches to a warning icon — never a check mark for something that did not work.
- The **result screen** shows the recovered PIN and passphrase together, with the same small success frame, and one Copy button.

The colour system is intentionally quiet: a paper background, white surfaces, thin rules, and two accents — green for capture, violet for the WPS audit. The cards have generous corners and a hairline outline instead of shadows, which keeps the screen calm and readable on a phone held at arm's length in a server room.

The interface is available in **English and French** only, and it is light-theme only. No third-party tool name appears anywhere in the visible UI; the licenses travel with the source and inside the app's About screen where they belong.

---

## The five-stage capture pipeline

The capture screen drives a single, clearly narrated operation. The stage titles and their plain-language
descriptions are part of the UI strings themselves, so what the user sees is always the same thing the code
does:

| Stage | Title (EN) | What the code does |
|---|---|---|
| 1 | Open the adapter | Open the USB adapter and tune to the target channel. |
| 2 | Monitor RX | Raw monitor receive: every frame on that channel is read. |
| 3 | Bounded deauth | Send a small number of deauth frames to clients seen on this BSSID. |
| 4 | Extract EAPOL | Pull EAPOL M1–M4 out of the captured frames and pair them. |
| 5 | Save pcap | Write the pcap to the chosen handshake folder. |

The operation log prints the same five steps as numbered notes. The stepper view renders a six-position
sequence (adapter, capture, PIN search, verify, PSK, done) while the capture flow itself runs its own
five-stage sequence.

### The window and the nudge

A capture is bounded to a fixed window (`CAPTURE_SECONDS = 120`). Nothing is sent to the network unless the
user starts the capture, and the consent dialog is shown before the first frame is transmitted:

> "Capture on your network — This records the WPA handshake of %s. It sends a small number of deauth frames to clients seen on this network to force a re-handshake. Continue only if you own this network or have written permission to test it."

The deauth phase is deliberately small: it measures how many frames were sent, how many were acknowledged,
and how many bursts were needed, and it is aimed only at clients already observed on that BSSID.

### What gets reported as a result

The UI distinguishes four honest outcomes:

1. **Complete handshake captured** — a crackable pair was found. The screen shows frames, EAPOL messages,
   client, pair and crackable-pair count.
2. **Capture saved, but no complete handshake was seen** — a file was written, but it is not a success.
3. **No frame for this network during the window** — nothing was captured, nothing was saved.
4. **Capture failed** — an error was reported instead of a check mark.

The success banner is only shown when the validator returned a real pair; a warning icon is used when the
capture failed or when no valid pair was found.

## The file that gets written

- The pcap is written only after the bundled validator confirms a crackable pair. A partial capture may be
  stored, but a partial capture is never presented as a valid handshake.
- The published path is `Download/<handshake folder>/<name>.pcap`.
- The capture log lines are *"Complete handshake saved: …"* / *"Partial capture saved: …"*.
- The EAPOL payload is labelled per message: `handshake_complete` reports `M<message number>`.

For offline analysis, the pcap uses linktype `105`, so it can be read with `hcxpcapngtool` and then fed to
`hashcat -m 22000`.

## The error taxonomy

The engine reports a small, closed set of failure kinds, and the UI maps them carefully:

- `no_m1` is never shown as "wrong PIN". It is surfaced as *"the router did not start a WPS session"*, and the
  attempt is stopped rather than retried.

The old behaviour could tell a user their PIN was wrong when the real problem was that no session ever started.
The new behaviour stops the run and leaves the user with an accurate statement.

## The result and history

- Recovered values (WPS PIN and Wi-Fi password) are shown together on the result screen, in one success frame
  with a short vibration, a heavier monospace line, and a single copy action.
- The handshake entry in history keeps `complete`, `valid_pairs`, `eapol_frames`, `frames` and the pair/client
  identifiers, so a previous run can be re-examined without re-capturing.

## The code

The full source, build instructions, release notes and the signed APK are here:

**https://github.com/mohadexter/Pixie-Dust-for-android-without-root**

GPL-2.0. Java and XML for the interface, Python for the engine, libusb for the radio, and no root anywhere in the stack.

If you build it, test it on your own hardware and your own network. That is the only testing that counts.
