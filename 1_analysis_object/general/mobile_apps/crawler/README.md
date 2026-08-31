# crawler

Scripts for downloading and converting Android APK packages.

## Scripts

| Script | Purpose |
|---|---|
| `fetch_apk.py` | Download APKs from APKPure |
| `convert_apk.py` | Convert XAPK / APKM / AAB → plain APK |

## Setup

```bash
pip install -r requirements.txt
```

For `convert_apk.py`, two external JARs are also needed — place them in the `tools/` subdirectory:

| File | Source |
|---|---|
| `tools/APKEditor.jar` | https://github.com/REAndroid/APKEditor/releases |
| `tools/bundletool.jar` | https://github.com/google/bundletool/releases (only for `.aab` input) |

Java 11 or later must be on `$PATH`.

---

## fetch_apk.py

Downloads APKs from APKPure. Downloaded files land in `../downloads/<package_name>/` and may be `.apk` or `.xapk` format.

```bash
# Download latest version
python fetch_apk.py com.tuya.smart

# List available versions (up to 20, no download)
python fetch_apk.py com.tuya.smart --list-versions

# Download a specific version by version code
python fetch_apk.py com.tuya.smart --version 123456789

# Download to a custom directory
python fetch_apk.py com.tuya.smart -o /tmp/apks/

# Batch download all apps in iot_app_list.json
python fetch_apk.py --batch ../iot_app_list.json
```

---

## convert_apk.py

Converts downloaded packages to a single, JADX-ready APK.

- **XAPK / APKM**: extracts the arm64-v8a + best-density splits and merges them with APKEditor into one APK.
- **AAB**: uses bundletool to generate device-specific splits (arm64, API 30), then merges with APKEditor.
- **APK**: copied to the output directory unchanged.

If APKEditor merge fails, the script falls back to `base.apk` only (sufficient for most static analysis).

```bash
# Convert a single file
python convert_apk.py app.xapk
python convert_apk.py app.apkm --output ./converted/
python convert_apk.py app.aab  --arch armeabi-v7a

# Batch convert all supported files in a directory
python convert_apk.py ../downloads/ --batch --output ../converted/
```

Output files are named `<stem>_merged.apk` (or `<stem>_base.apk` on fallback).

---

## Typical workflow

```bash
# 1. Download
python fetch_apk.py com.tuya.smart

# 2. Convert (if the download is an XAPK)
python convert_apk.py ../downloads/com.tuya.smart/*.xapk

# 3. Analyse with JADX
jadx ../downloads/com.tuya.smart/converted/com.tuya.smart_merged.apk
```
