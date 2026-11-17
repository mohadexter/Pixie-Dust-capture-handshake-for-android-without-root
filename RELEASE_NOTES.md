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
   - License and NOTICE files still ship with the source and satisfy the GPL-3.0
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
