# Pixie Dust 1.0.9 - RTL8188FTV, Radio Switch Fix, Donations

Release number: 1.0.9 (versionCode 10).

New adapter support, the RTL8187 false alarm fix, and the support/donation surfaces.
Capture, PIN recovery and history are unchanged.

## What is new in this release

1. **RTL8188FTV support (`0bda:f179`)**
   - Clean-room port of the vendor DKMS driver (`v4.3.23.6_20964.20170110`), 2.4 GHz only.
   - Bundled firmware `rtl8188fufw.bin` (21 KB) ships inside the APK and is uploaded at bring-up.
   - Full bring-up: EFUSE/prom parse, power sequence, IQK/BB calibration, RF init, monitor mode, channel hops, TX/RX rings, watchdog.
   - Verified with the chip's 183 unit tests (wire-level expectations) before packaging.

2. **RTL8187 "radio switch reads OFF" is no longer fatal**
   - The kernel registers the RFKILL pin as a *polling* rfkill and still brings the card up; this app used to abort instead.
   - Several RTL8187 clones have no physical switch (floating or inverted pin), so a hard failure blocked working dongles.
   - The probe now also cross-checks mask `0x01`, logs the raw GPIO readings, and continues bring-up with a clear progress note.

3. **Telegram icon and donations**
   - The support entry now uses the official Telegram mark, in brand blue.
   - A **Join Telegram support** button sits in About, under **Release notes**.
   - BTC / ETH / LTC / SOL / TRX icons sit directly under the Telegram entry in About and Support; one tap copies the address.

4. **Details**
   - Header icons use the same ink colour (history, settings, Telegram).
   - The language row's action button now reads **Change** / **Modifier** instead of a second « Language » label.

## Verification

- Package `ma.pixiedust.app`, versionCode 10, versionName 1.0.9, minSdk 24,
  targetSdk 36, `arm64-v8a` + `armeabi-v7a`.
- Signed with the existing release key (`apksigner` certificate SHA-256
  `18fab906...`).

---

## Verification

- Package `ma.pixiedust.app`, versionCode 10, versionName 1.0.9, minSdk 24,
  targetSdk 36, `arm64-v8a` + `armeabi-v7a`.
- Signed with the existing release key (`apksigner` certificate SHA-256
  `18fab906...`).

---

# Pixie Dust 1.0.8 — Adapter Diagnostics, Cleaner Highlights, Launch Update Check

Release number: 1.0.8 (versionCode 9).

This release is a maintenance and interface pass. No capture, PIN-recovery or
history behaviour changed.

## What is new in this release

1. **RTL8187 radio detection**
   - The rfkill GPIO is sampled repeatedly and cross-checked against both known
     masks (`0x2` and `0x4`) before the adapter is declared switched off. This
     removes false "hardware radio switch reads OFF" failures on dongles with no
     physical switch.
   - A genuine switch that stays off is still respected; the error now carries
     the raw GPIO readings and a clear English/French instruction.

2. **English/French only**
   - The remaining Arabic/Darija strings in the Python CLI layer were replaced,
     including the "router didn't start a WPS session" message.

3. **Smarter known-model highlight**
   - Generic labels such as `Wireless AP` or `Wireless Access Point` no longer
     make a network look supported. A real model token is required.
   - 699 additional model strings from public WPS/Pixie-Dust databases were
     merged into the offline list; the original 142 field-reported entries,
     including firmware placeholders, were kept untouched.

4. **Update check on every app entry**
   - With a connection, GitHub is checked on each foreground visit; the request
     is non-blocking and silent on failure.
   - **Check for updates** moved from **About** to a new **Updates** card in
     **Settings**. Download, verification and explicit install are unchanged.

5. **Support**
   - A Telegram support button (`https://t.me/PixieDustapp`) sits in the scan
     screen header.

## Verification

- Package `ma.pixiedust.app`, versionCode 9, versionName 1.0.8, minSdk 24,
  targetSdk 36, `arm64-v8a` + `armeabi-v7a`.
- Signed with the existing release key (`apksigner` certificate SHA-256
  `18fab906...`).

---

# Pixie Dust 1.0.7 — Optional In-App Updates

Release number: 1.0.7 (versionCode 8).

Version 1.0.7 adds an update channel that is entirely optional. Pixie Dust checks
GitHub at most once a day, says when a newer release exists, and never downloads
or installs anything without a tap. Nothing about scanning, capturing or history
changes in this release.

## What is new in this release

1. **Automatic, non-blocking check**
   - One HTTPS request for `docs/update.json`, at most once every 24 hours.
   - A failed request is silent and keeps the previous cached answer.
   - A low-priority notification is posted when a newer version exists.

2. **Download and verification**
   - The APK is fetched with `DownloadManager` into the app's own folder, so no
     storage permission is added.
   - The file must match the published **SHA-256** and be signed with the same
     certificate as the installed app; otherwise it is deleted and the install
     is refused.

3. **What's new in three places**
   - In the update dialog before downloading.
   - On the first launch after an update, **offline**, from the changelog bundled
     in the APK (`res/raw/update_changelog.json`, generated from `docs/update.json`).
   - From **About → Release notes**, with the full history.

4. **Explicit install**
   - A "ready to install" notification opens a small screen that verifies the file
     again, then opens the Android system installer.
   - "Later" is always available; a dismissed release is not raised again until a
     newer one appears.

5. **Corrected wording**
   - The About screen and the README no longer claim that the app has no network
     access. The `INTERNET` permission exists only for this optional update check;
     captured data is never transmitted.

## Verification

- Package `ma.pixiedust.app`, versionCode 8, versionName 1.0.7, minSdk 24,
  targetSdk 36, `arm64-v8a` + `armeabi-v7a`.
- Signed with the existing release key (`apksigner` certificate SHA-256
  `18fab906...`).

---

# Pixie Dust 1.0.6 — Known Models, Split History, Storage First

Release number: 1.0.6 (versionCode 7).

Version 1.0.6 is a focused interface release: the scan list now points at the
routers this tool is meant for, the history screen separates handshakes from
PixieDust results, and the handshake folder is the first thing Settings shows.

## What is new in this release

1. **Known-router highlight in the scan list**
   - `res/raw/known_models.txt` ships the router models, chipset strings and
     firmware placeholders that PixieDust users meet in the field (TL-WR841N,
     TL-MR3020, Archer C50, DIR-605L, NBG-418N, RT2860, RTL8xxx, ...).
   - Matching is tolerant: compact comparison (letters and digits only, lower
     case), a trailing hardware version is dropped, and a substring match is
     accepted in both directions, so `TP-LINK Wireless Router TL-WR841N` still
     matches `TL-WR841N`.
   - When a network reports a known model its **SSID is drawn in green**, and a
     green **Pixie** pill sits next to the **WPS** pill.
   - Nothing is downloaded: the list is a resource inside the APK.

2. **History split in two**
   - Two tabs with live counts: **Handshake (n)** and **PixieDust (n)**.
   - Clear removes only the visible tab, with a tab-specific confirmation.
   - The empty state follows the selected tab.

3. **History icon**
   - The header button and the empty state now use a clock-with-arrow icon
     instead of a folder.

4. **Handshake storage first**
   - The **Handshake storage** card is the first block in Settings, above
     scanning, attack defaults, language and adapter.

## Unchanged on purpose

- No new permission, no network access, no telemetry.
- Light paper theme, English and French only.
- Capture, PixieDust and history logic untouched.

## Verification

- Built with `assembleRelease` and the existing release key (`apksigner`
  certificate SHA-256 `18fab906...`).
- Package `ma.pixiedust.app`, versionCode 7, versionName 1.0.6, minSdk 24,
  targetSdk 36, `arm64-v8a` + `armeabi-v7a`.

---

# Pixie Dust 1.0.5 — Handshake Folder, Signal Sorting, Live Clients

Release number: 1.0.5 (versionCode 6).

Version 1.0.5 focuses on the capture workflow and the network list: where handshakes
are saved, how networks are ordered, how vendor/model survive between scans, and a
client table that really follows joins and disconnections. It also narrows the app to
English and French and removes the visible third-party product name.

## What is new in this release

1. **Handshake folder is `Download/Hanshake`**
   - Captured pcaps are published to `Download/Hanshake`, never under `Android/data`.
   - Settings now has a **Handshake storage** card showing the current destination.
   - Options: default `Download/Hanshake`, the system folder picker (SAF, write access
     persisted), or a custom folder name under Download.

2. **Network list sorted by signal**
   - Strongest RSSI first, on every scan. The WPS-first grouping was removed.

3. **Vendor and model on every scan**
   - WSC manufacturer/model information now upgrades the OUI fallback whenever a
     later beacon carries it (it is never overwritten with a blank value).
   - Learned vendor/model pairs are cached on-device and reused when a scan misses
     the WSC information element, so the line no longer appears only sometimes.

4. **Live client table fixed**
   - Capture publishes MAC + RSSI snapshots every 0.5 s and immediately when a new
     station appears.
   - A deauth/disassoc removes that station at once; a silent station expires after
     45 s. The list therefore follows both associations and disconnections.
   - The capture screen shows the count in the card title and refreshes on its own
     timer as well as on engine snapshots.

5. **English and French only**
   - Arabic resources and the Arabic language choice were removed; a stored Arabic
     preference migrates to the system language.
   - `locales_config.xml` and the language selector now list only English/French.

6. **No visible third-party branding**
   - The `MONITOR` pill above the network list is gone.
   - The About screen no longer displays the bundled validator's project name.
   - License and NOTICE files still ship with the source and satisfy the GPL-2.0
     obligations; internal use of the validator in code is unchanged.

7. **Handshake validation unchanged and safe**
   - A pcap is written only after the bundled validator finds a crackable pair.
   - Stopping a capture never leaves an empty or invalid file.
   - `no_m1` is still reported as "router did not start a WPS session", never as a
     wrong PIN; the PIN and PSK are shown together without an empty PSK card.

8. **Visual refresh of the network actions and capture flow**
   - The network sheet now shows "Capture WPA handshake" (green) and "PixieDust
     attack" (violet) as two equal, white, 26 dp cards with a thin grey outline,
     a rounded icon tile, a title and a one-line explanation. Behaviour is
     unchanged.
   - The scan header uses the app icon; the screen is titled "Scan network".
   - The capture screen has one main button that reads "Start capture handshake"
     and becomes "Stop capture" while it runs. The folder line and the separate
     stop button were removed.
   - A failed or stopped capture now shows a warning icon instead of a check mark.
   - On success, a small frame shows the result: the file path (in heavier
     monospace) with "Open file" and "Copy path" for a handshake, and the recovered
     PIN/password with "Copy" for a PixieDust run. It also gives a short vibration.
   - The unused "Devices in this network" panel was removed from the capture screen.
   - Fix: the two action cards used a 0 dp height inside a wrap-content layout, so
     they collapsed to nothing. They now size to their content and share one height,
     so both options are visible on every screen size.

## Verification and delivery

Build: `:app:assembleRelease` with the release signing configuration.
Checks to run after the build: `apksigner verify --print-certs`, `aapt2 dump badging`
(package `ma.pixiedust.app`, versionCode 6, versionName 1.0.5, arm64-v8a and
armeabi-v7a), and SHA-256 of the APK.

No real-device test is claimed. USB OTG bring-up, radio capture, client monitoring and
the bounded deauth still need physical hardware testing.
