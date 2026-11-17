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

There is no retry loop. If the router rejects the attempt, or if it is not vulnerable at all, the app says so and stops. That single-attempt rule is deliberate: it is both the ethical boundary and the technical one, since modern routers lock WPS after a handful of failures.

### 2. WPA 4-way handshake capture

The second job is the classic one. The app tunes to the target network, listens to the channel, and waits for a client to authenticate so it can record the four-way handshake. If no client reconnects on its own, a **bounded and targeted** deauthentication burst nudges the clients already observed on that BSSID into reconnecting.

The important part is what happens next. A capture is only reported as a success if the bundled validator finds a **crackable pair** — an actual M1/M2 pair from the same session. If no valid pair was found, no `.pcap` file is written at all.

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

The single most important design decision is that **exactly one thread ever talks to the USB device**. The engine runs on a dedicated `pixie-engine` thread, and every operation — scan, capture, WPS attempt — is serialised through it.

The UI never blocks on the engine. It reads a single observable state object (`Repo`) and redraws. Because the update callback is posted to the main thread, there is no locking in the UI code and no chance of touching a View from a background thread.

### Getting libusb to work on Android without root

On a desktop, libusb opens a device by path. On Android, the USB device node under `/dev/bus/usb/` is not readable by an ordinary app. An app *can* get a **file descriptor** from the system, after the user grants permission through the standard OTG dialog.

The bridge therefore hands libusb an already-open descriptor instead of a device path, and lets libusb wrap it. The bundled `libusb_fd.py` module handles that handover and the platform quirks. The notable one is `libusb_get_configuration` failing with `Operation not permitted` on some chipset/phone combinations, which the module works around.

There is a second, less obvious problem: native libraries must exist as **real files on disk**, not inside the APK's zip. The build is configured with `useLegacyPackaging = true` to force extraction at install time, because the Python binding loads libusb with `ctypes.CDLL(<nativeLibraryDir>/libusb-1.0.so)`.

The Python packages that carry firmware blobs are likewise extracted rather than imported from the archive, because the drivers read them as files.

### Supported hardware

| Group | Chipset | Adapter | Bands |
|---|---|---|---|
| Ralink | RT5370 / RT5372 / RT5572 / RT3070 / RT2570 | — | 2.4 / 2.4-5 |
| MediaTek | MT7601U / MT7610U / MT7612U / MT7921AU / MT7925U | — | 2.4 / 2.4-5 / 2.4-5-6 |
| Atheros | AR9271 | AWUS036NHA | 2.4 GHz |
| Realtek | RTL8187 / RTL8188 / RTL8192 / RTL8812AU / RTL8814AU / RTL8821AU / RTL8822BU / RTL8922AU / RTL8811CU / RTL8822CU | — | 2.4 / 2.4-5 / … |
| TP-Link | RTL8192EU / RTL8188 / Archer T2U Plus | TL-WN823N, TL-WN722N, Archer T2U Plus | 2.4 / 2.4-5 |

Only ARM is shipped — `arm64-v8a` and `armeabi-v7a`.

---

## The interface

The app is designed to be usable by someone who has never run a Wi-Fi audit before, without hiding what it is doing.

- **Scan network** lists nearby access points, strongest signal first, with manufacturer and router model.
- Tapping a network opens a sheet with technical facts — BSSID, channel, encryption, WPS version, client count — and exactly two equal cards: **Capture WPA handshake** and **PixieDust attack**.
- The **capture screen** walks through five stages with a live stepper, a plain-language stage explanation, and one button toggling *Start capture handshake* / *Stop capture*.
- On success a small frame shows the file path (Open file / Copy path); on failure a warning icon is shown.
- Available in **English and French** only, light theme only.

---

## The five-stage capture pipeline

| Stage | Title (EN) | What the code does |
|---|---|---|
| 1 | Open the adapter | Open the USB adapter and tune to the target channel. |
| 2 | Monitor RX | Raw monitor receive: every frame on that channel is read. |
| 3 | Bounded deauth | Send a small number of deauth frames to clients seen on this BSSID. |
| 4 | Extract EAPOL | Pull EAPOL M1–M4 out of the captured frames and pair them. |
| 5 | Save pcap | Write the pcap to the chosen handshake folder. |

A capture is bounded to a fixed window (`CAPTURE_SECONDS = 120).

---

## The file that gets written

- The pcap is written only after the bundled validator confirms a crackable pair.
- The published path is `Download/<handshake folder>/<name>.pcap`.
- The capture log lines are *"Complete handshake saved: …"* / *"Partial capture saved: …"*.
- The EAPOL payload is labelled per message: `handshake_complete` reports `M<message number>`.

For offline analysis, the pcap uses linktype `105`, so it can be read with `hcxpcapngtool` and then fed to
`hashcat -m 22000`.

---

## The error taxonomy

- `no_m1` is never shown as "wrong PIN". It is surfaced as *"the router did not start a WPS session"*, and the
  attempt is stopped rather than retried.

The old behaviour could tell a user their PIN was wrong when the real problem was that no session ever started.
The new behaviour stops the run and leaves the user with an accurate statement.

---

## The result and history

- Recovered values (WPS PIN and Wi-Fi password) are shown together on the result screen, in one success frame
  with a short vibration, a heavier monospace line, and a single copy action.

---

## The code

The full source, build instructions, release notes and the signed APK are here:

**https://github.com/mohadexter/Pixie-Dust-for-android-without-root**

GPL-2.0. Java and XML for the interface, Python for the engine, libusb for the radio, and no root anywhere in the stack.

If you build it, test it on your own hardware and your own network. That is the only testing that counts.
