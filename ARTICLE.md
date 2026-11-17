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

The UI never blocks on the engine. It reads a single observable state object (`Repo`) and redraws.

### Getting libusb to work on Android without root

On a desktop, libusb opens a device by path. On Android, the USB device node under `/dev/bus/usb/` is not readable by an ordinary app. An app *can* get a **file descriptor** from the system, after the user grants permission through the standard OTG dialog.

The bridge hands libusb an already-open descriptor instead of a device path. The bundled `libusb_fd.py` handles that handover and the platform quirks. The notable one is `libusb_get_configuration` failing with `Operation not permitted` on some chipset/phone combinations, which the module works around.

Native libraries must exist as **real files on disk**, not inside the APK's zip. The build uses `useLegacyPackaging = true` so libusb is extracted at install time; otherwise the app installs fine and fails at the first USB call.

### Supported hardware

The driver stack covers a wide range of USB adapters:

| Group | Chipset | Adapter | Bands |
|---|---|---|---|
| Ralink | RT5370 / RT5372 / RT5572 / RT3070 / RT2570 | — | 2.4 / 2.4-5 |
| MediaTek | MT7601U / MT7610U / MT7612U / MT7921AU / MT7925U | — | 2.4 / 2.4-5 / 2.4-5-6 |
| Atheros | AR9271 | AWUS036NHA | 2.4 GHz |
| Realtek | RTL8187 / RTL8188 / RTL8192 / RTL8812AU / RTL8814AU / RTL8821AU / RTL8822BU / RTL8922AU / RTL8811CU / RTL8822CU | — | 2.4 / 2.4-5 / … |
| TP-Link | RTL8192EU / RTL8188 / Archer T2U Plus | TL-WN823N, TL-WN722N, Archer T2U Plus | 2.4 / 2.4-5 |

Only ARM is shipped — `arm64-v8a` and `armeabi-v7a` — because the firmware blobs and the driver are
architecture-specific and because x86 has no OTG radio to talk to anyway.

---

## The interface

The app is designed to be usable by someone who has never run a Wi-Fi audit before, without hiding what it is doing.

- **Scan network** lists nearby access points, strongest signal first, with manufacturer and router model.
- Tapping a network opens a compact sheet with technical facts — BSSID, channel, encryption, WPS version,
  client count — and exactly two actions as equal cards: **Capture WPA handshake** and **PixieDust attack**.
- The **capture screen** walks through five stages with a live stepper, a plain-language stage explanation, and
  one button toggling *Start capture handshake* / *Stop capture*.
- On success a small frame shows the file path (Open file / Copy path); on failure a warning icon is shown.

The interface is available in **English and French** only, and it is light-theme only.

---

## The code

The full source, build instructions, release notes and the signed APK are here:

**https://github.com/mohadexter/Pixie-Dust-for-android-without-root**

GPL-2.0. Java and XML for the interface, Python for the engine, libusb for the radio, and no root anywhere in the stack.

If you build it, test it on your own hardware and your own network. That is the only testing that counts.
