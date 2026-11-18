# Pixie Dust

![Pixie Dust social preview](docs/social-preview.png)

**Pixie Dust is a security auditing app for Android.** It checks the security of **WPS** on a wireless network — and can capture the **WPA 4-way handshake** — over a **USB OTG** adapter, **without root**, **without `wpa_supplicant`**, and with **no account and no telemetry**.

> **Only test networks you own or have explicit written permission to test.** The app asks for confirmation before every operation and requires written-authorization intent before it transmits anything. Misuse against networks you do not own is illegal in most jurisdictions.

## Quick links

| | |
|---|---|
| 📦 **Latest release (APK)** | [releases/tag/v1.0.9](../../releases/tag/v1.0.9) |
| 📖 **Technical write-up** | [ARTICLE.md](ARTICLE.md) |
| 🛠️ **Build instructions** | [README-BUILD.md](README-BUILD.md) |
| 🧾 **Release notes** | [RELEASE_NOTES.md](RELEASE_NOTES.md) |
| 💬 **Support / community** | [t.me/PixieDustapp](https://t.me/PixieDustapp) |

## What it does

- **Pixie Dust WPS audit** — one user-confirmed PIN attempt per run. On vulnerable routers, the PIN is recovered offline from the M1–M3 exchange and validated with a single M4–M7 transaction.
- **WPA handshake capture** — captures a crackable M1/M2 pair, validates it, and saves a `pcap` your file manager can open (`hcxpcapngtool`-compatible).
- **Known-model hint** — the scan list highlights routers reported as WPS-weak (offline database, 800+ entries), and separates handshakes from PixieDust results in history.
- **Optional in-app updates** — checks GitHub on launch, downloads only with your tap, verifies SHA-256 and the signing certificate. Nothing is forced.

## Screenshots

| Scan | Network details | Capture | Result |
|---|---|---|---|
| ![Scan](docs/screenshots/screen1.jpg) | ![Network details](docs/screenshots/screen2.jpg) | ![Capture](docs/screenshots/screen3.jpg) | ![Result](docs/screenshots/screen4.jpg) |

## Requirements

| | |
|---|---|
| Android | 7.0 (API 24) or newer — up to Android 16 |
| Phone | USB OTG support; high-power adapters may need a powered hub |
| Adapter | A supported USB Wi-Fi adapter (RT5370, RT5572, AR9271, RTL8187, RTL8812AU… see [ARTICLE.md](ARTICLE.md) for the full table) |
| Languages | English, French |
| ABIs | `arm64-v8a`, `armeabi-v7a` |

## Safety and privacy

- One PIN attempt per run. **No retries, no online PIN guessing, no PBC/WEP, no OneShot.**
- Deauthentication during capture is bounded and targeted — never a flood.
- Recovered PINs/passwords **never leave the device**; clear History in the app to delete them.
- The only network traffic is the optional update check (`docs/update.json`); captured data is never transmitted.

## Status

This tree builds release **1.0.9** (versionCode **9**). Please verify the APK with `apksigner` before installing; no physical-adapter test is claimed here — if you build it, test on your own phone and your own network.

## License

**GPL-2.0** — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
