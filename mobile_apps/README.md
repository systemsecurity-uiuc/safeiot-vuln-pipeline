# Mobile Apps

Tooling for collecting and preparing mainstream IoT Android applications for security analysis (e.g. with JADX), in support of the SafeIoT / Lalaine research pipeline.

## Structure

```
mobile_apps/
├── crawler/            # Download and conversion scripts
│   ├── fetch_apk.py    # Download APKs from APKPure
│   ├── convert_apk.py  # Convert XAPK / APKM / AAB → plain APK
│   ├── requirements.txt
│   ├── tools/          # Place APKEditor.jar and bundletool.jar here (gitignored)
│   └── README.md
├── downloads/          # Downloaded APK packages — gitignored, not committed
└── iot_app_list.json   # Recommended IoT apps with Android package names
```

## Quick start

```bash
cd crawler
pip install -r requirements.txt

# Download latest Tuya Smart APK
python fetch_apk.py com.tuya.smart

# Convert the downloaded XAPK to a plain APK
python convert_apk.py ../downloads/com.tuya.smart/*.xapk

# Batch-download all apps in the recommended list
python fetch_apk.py --batch ../iot_app_list.json
```

See [crawler/README.md](crawler/README.md) for full usage and dependency setup.

## Recommended app list

`iot_app_list.json` contains 22 widely-deployed IoT companion apps covering major platforms (Google Home, Alexa, SmartThings, Tuya, Xiaomi), security cameras, smart lighting, and open-source controllers (Home Assistant). Each entry includes the Android package name, vendor, Matter support status, and a short note.
