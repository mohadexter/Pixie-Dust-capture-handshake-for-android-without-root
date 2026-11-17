# Pixie Dust — Project README

## Short description

**Pixie Dust** is a security app for Android that audits the security of **WPS** (Wi-Fi Protected Setup) on wireless networks over a **USB OTG** port.

The app is written in **Java + XML** with an internal **Python** engine, and runs on the embedded **libusb** engine. Its goal: audit a **PIN**, then extract the **PSK**, without root, without `wpa_supplicant`, without internet, and with a single attempt only.

## Features

- **Pixie Dust WPS audit** with one user-confirmed PIN attempt per run; the supported model and router behavior determine whether a PIN or PSK is returned.
- **WPA 4-way handshake capture** is validated by the bundled handshake validator before a pcap is saved; invalid or incomplete captures are reported and never presented as valid files.
- **Live client table** during scans and capture, showing observed client MAC addresses and signal strength. It follows a device when it appears and removes it when it disconnects.
- **Network list sorted by signal strength** (strongest first) and showing the manufacturer and, when known, router model. Manufacturer/model values are cached on-device, so a later scan that misses the WPS information element still shows the same router.
- **Handshake storage in `Download/Hanshake`** (not `Android/data`), with a Settings option to pick another system folder or a custom folder name.
- **Results and private history** show verified captures and credentials recovered on-device. History is stored locally and is not sent over the network.
- **English and French** interface; light theme only.
- No third-party product name is displayed in the interface; the required license and NOTICE files still ship with the source and the app.

## Technical architecture

- UI: Java + XML, two locales: English, French.
- Engine: Python 3.11 (Chaquopy) + libusb 1.0.30.
- ABIs: arm64-v8a + armeabi-v7a (no x86, no emulator).
- Signing: release, v2, certificate SHA-256 `18fab90662b96344e4548c36bcc5eebbb7c714582af2b120b746cdbfcfabb17c`.

## Build and verification status

This source tree builds release `1.0.5` (versionCode `6`). Verify the produced APK with `apksigner` before installing it, and check the package/version with `aapt2 dump badging`.

Physical testing with an Android phone and a supported USB OTG Wi-Fi adapter is still required. No real-device test is claimed here.

## Safety and privacy

- WPS validation makes one attempt only; no automatic retries, online PIN guessing, OneShot, PBC/WEP, root, or `wpa_supplicant`.
- Optional deauthentication during a capture is bounded and targeted; it is not a flood. Use only on networks you own or are authorized to test.
- Recovered PINs/passwords are stored in the app-private on-device history. Clear history in the app to remove those records. The app has no `INTERNET` permission and does not transmit this history.
- No real-device functionality is claimed until tested with compatible hardware.

---

## End of README
