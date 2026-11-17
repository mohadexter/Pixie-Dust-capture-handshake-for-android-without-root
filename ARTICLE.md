# Pixie Dust: Auditing WPS and WPA Security from an Android Phone, Without Root

*A technical walkthrough of a native Android app that runs a complete USB Wi-Fi security audit on a phone, with no root, no `wpa_supplicant`, and no internet permission.*

---

## Why this project exists

Most Wi-Fi security tooling lives on a laptop. You install a Linux distribution, patch a driver to support monitor mode and packet injection, plug in a compatible USB adapter, and start `aircrack-ng`, `reaver`, or `hashcat`. It works, but it is heavy. It needs a second machine, a specific operating system, and a stack of driver patches that break with every kernel update.

Phones are the opposite: always with you, always charged, and — thanks to USB On-The-Go — perfectly capable of hosting a USB Wi-Fi adapter. What has been missing is the software layer that makes that hardware usable on unrooted Android.

**Pixie Dust** is an attempt to fill that gap. It is a single Android application, written in Java with an embedded Python engine, that brings a WPS audit and a WPA handshake capture to an ordinary phone. It does not require root, it does not touch `wpa_supplicant`, and it cannot send anything over the network, because it does not even request the `INTERNET` permission.

The project is open source under GPL-3.0:

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

## Storage, privacy and the missing permission

Recovered data is written to `Download/Hanshake` by default, not to `Android/data`, so a user can find the files with an ordinary file manager. A Settings screen allows choosing another system folder — the app uses the Storage Access Framework, so no storage permission is requested on modern Android — or a custom folder name.

Files saved this way are handed back to the user as a content URI, which is what makes the **Open file** button work without exposing the filesystem. Where no URI exists, a narrowly scoped `FileProvider` covers `Download/` and the staging cache.

The privacy posture is simple and verifiable:

- **No `INTERNET` permission.** Not a policy, a manifest fact. The application physically cannot transmit anything.
- The history of recovered PINs and passphrases is stored in app-private storage and can be erased from the History screen.
- Credentials are never written to logcat.
- A disclaimer is accepted once at first launch, and every operation needs an explicit confirmation before it runs.

---

## Safety rules, encoded rather than promised

A security tool is only as good as the constraints it enforces on itself. In this codebase those constraints are structural:

| Rule | Where it lives |
|---|---|
| One WPS attempt per run, no automatic retries | `auto_attack(..., auto_verify)` in the engine |
| No OneShot, no online PIN guessing, no PBC/WEP | Not implemented anywhere in the engine |
| Bounded, targeted deauth — never a flood | Deauth targets only clients observed on that BSSID, in a short burst |
| No pcap unless a crackable pair is validated | `Repo` publishes the file only after the validator agrees |
| `no_m1` reported as "the router did not start a WPS session" | `PixieError` mapping — never as "wrong PIN" |
| Application must be in the foreground to keep working | Foreground service with an explicit notification |

That last row deserves a note. The engine runs inside a foreground service with a wake lock and a persistent notification. If the process is killed, the USB session dies with it, so the app makes that state visible instead of silently continuing to show a stale progress bar.

---

## Build and verification

The project builds a signed release APK with the Gradle wrapper:

```powershell
$env:JAVA_HOME="C:\Java\jdk-21.0.13+9"
$env:PATH="C:\Python311;C:\Python311\Scripts;$env:PATH"
.\gradlew.bat :app:assembleRelease
```

Requirements: JDK 17 or newer, Android SDK platform 36 with build tools 36, and **Python 3.11** — Chaquopy 17.2 pins 3.11 for the 32-bit ARM target, so a newer interpreter will not do.

The output is verified with the standard tooling rather than assumed to be correct:

```
$ apksigner verify --print-certs app-release.apk
Signer #1 certificate DN: CN=Pixie Dust, OU=Mobile, O=PixieDust, L=Casablanca, ...
Signer #1 certificate SHA-256 digest: 18fab90662b96344e4548c36bcc5eebbb...
Verified using v2 scheme (APK Signature Scheme v2): true

$ aapt2 dump badging app-release.apk
package: name='ma.pixiedust.app' versionCode='6' versionName='1.0.5'
native-code: 'arm64-v8a' 'armeabi-v7a'
```

The release is minified with R8 and resource-shrunk. The APK lands around 30 MB, most of which is Python 3.11, the driver stack, and firmware blobs for the supported chipsets.

---

## An honest list of limits

No security project is complete without saying what it does not do, and this one has meaningful limits.

**It has not been validated on a physical phone with an OTG adapter in the development environment.** The build compiles, the APK is signed and installs, and the UI runs — but radio behaviour, actual frame capture, deauth delivery and handshake validation on real hardware are separate questions. Until they are tested on a device, the app should be treated as a working build, not a proven tool. The README says exactly this, on purpose.

**WPS success depends on the router.** Pixie Dust exploits weakness in a specific class of random number generators. Many modern routers use protections that defeat it outright, and some lock WPS permanently after a few failures. A failed attempt is the normal outcome on current hardware.

**Capture success depends on traffic.** A network with no clients, or with clients that never reconnect, will not yield a handshake. The deauth nudge helps but cannot create traffic that is not there.

**Client counting is an estimate.** The number shown comes from unicast MAC addresses observed in data frames on the channel. It is not a query to the router's association table, and it will not match what the router's admin page reports.

**Phone radios cannot do this.** The built-in Wi-Fi chipset does not expose monitor mode to applications. The app is only useful with a supported USB adapter and an OTG cable, and the phone must be able to power that adapter — high-power adapters may need a powered hub.

---

## What building this taught me

Three lessons stand out.

**Android is a viable host for serious RF tooling.** The file-descriptor route into libusb removes the root requirement entirely, and once that works, the phone becomes a legitimate platform rather than a toy. The remaining friction is power delivery and thermal headroom, not permissions.

**Refusing to report false success is a feature.** Requiring a validated handshake pair before writing a file costs a little complexity and removes an enormous amount of user confusion. The same principle applies to the WPS side, where reporting `no_m1` as "the router did not start a WPS session" instead of "wrong PIN" changes what the user does next.

**Constraint is what makes a security tool trustworthy.** One attempt. One thread on the radio. No internet permission. A visible confirmation before anything is transmitted. None of these make the app more capable — they make it something a person can responsibly run on their own network.

---

## The code

The full source, build instructions, release notes and the signed APK are here:

**https://github.com/mohadexter/Pixie-Dust-for-android-without-root**

GPL-3.0. Java and XML for the interface, Python for the engine, libusb for the radio, and no root anywhere in the stack.

If you build it, test it on your own hardware and your own network. That is the only testing that counts.
