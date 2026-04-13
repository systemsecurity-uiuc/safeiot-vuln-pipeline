#!/usr/bin/env python3
"""
convert_apk.py — Convert downloaded APK packages to JADX-ready plain APK.

Supported input formats
-----------------------
  .apk   Already a plain APK — copied to output directory as-is.
  .xapk  APKPure split-APK bundle (ZIP containing base.apk + config splits).
  .apkm  APKMirror split-APK bundle (same ZIP layout as XAPK).
  .aab   Android App Bundle — converted via bundletool, then splits merged.

Conversion strategy
-------------------
Split APKs (XAPK / APKM) are merged into a single installable APK using
APKEditor (https://github.com/REAndroid/APKEditor).  Only the arm64-v8a ABI
split and the highest available screen-density split are included, which keeps
the output lean while covering the dominant device class.

For .aab input, bundletool first generates a device-specific .apks archive
(targeting arm64-v8a, API 30), and the resulting splits are fed to APKEditor.

External tool requirements
--------------------------
Place the following JARs in the tools/ subdirectory next to this script:
  tools/APKEditor.jar   — download from https://github.com/REAndroid/APKEditor/releases
  tools/bundletool.jar  — download from https://github.com/google/bundletool/releases
                          (only needed for .aab input)
Java 11 or later must be on $PATH.

Usage
-----
  python convert_apk.py <file.xapk>
  python convert_apk.py <file.apkm> --output ./converted/
  python convert_apk.py <file.aab>  --arch armeabi-v7a
  python convert_apk.py ../downloads/ --batch
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths to external tools
# ---------------------------------------------------------------------------
TOOLS_DIR = Path(__file__).parent / "tools"
APKEDITOR_JAR = TOOLS_DIR / "APKEditor.jar"
BUNDLETOOL_JAR = TOOLS_DIR / "bundletool.jar"

DEFAULT_ARCH = "arm64-v8a"

# ABI strings that appear in split filenames (APKPure / Play Store naming)
ARCH_SPLIT_NAMES: dict[str, list[str]] = {
    "arm64-v8a": ["arm64_v8a", "arm64-v8a"],
    "armeabi-v7a": ["armeabi_v7a", "armeabi-v7a"],
    "x86_64": ["x86_64"],
    "x86": ["x86"],
}

# Screen densities in descending quality order — we keep the first match
DENSITY_PREFERENCE = ["xxxhdpi", "xxhdpi", "xhdpi", "hdpi", "mdpi"]


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

def _check_java() -> bool:
    """Return True if java is available on $PATH."""
    try:
        r = subprocess.run(
            ["java", "-version"], capture_output=True, timeout=10
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _require_java() -> None:
    if not _check_java():
        print("[!] Java not found. Install Java 11+ and ensure it is on $PATH.")
        sys.exit(1)


def _require_jar(jar: Path, name: str) -> None:
    if not jar.exists():
        print(f"[!] {name} not found at: {jar}")
        print(f"    Download it and place it there, then retry.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(path: Path) -> str:
    """
    Return one of: 'apk', 'xapk', 'apkm', 'aab', 'unknown'.
    """
    ext = path.suffix.lower()
    if ext in (".xapk", ".apkm", ".aab"):
        return ext[1:]  # strip leading dot

    if ext == ".apk":
        if not zipfile.is_zipfile(path):
            return "apk"
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        # A plain APK must have AndroidManifest.xml at the root
        if "AndroidManifest.xml" in names:
            return "apk"
        # Some downloads are labelled .apk but are actually split-APK ZIPs
        if any(n.endswith(".apk") for n in names):
            return "xapk"

    return "unknown"


# ---------------------------------------------------------------------------
# Split selection
# ---------------------------------------------------------------------------

def _select_splits(apk_names: list[str], arch: str) -> list[str]:
    """
    Given a list of APK filenames inside an archive, return the subset to
    include in the merge:
      - base.apk (always)
      - one arch-specific config split
      - one density config split (best available)
      - English locale config (if present)
    """
    arch_tokens = ARCH_SPLIT_NAMES.get(arch, [arch.replace("-", "_")])
    keep: list[str] = []

    base = next((n for n in apk_names if Path(n).name.lower() == "base.apk"), None)
    if base:
        keep.append(base)

    # Arch split
    for name in apk_names:
        bn = Path(name).name.lower()
        if any(tok in bn for tok in arch_tokens):
            keep.append(name)
            break

    # Density split — pick highest quality available
    for density in DENSITY_PREFERENCE:
        match = next(
            (n for n in apk_names if density in Path(n).name.lower()), None
        )
        if match:
            keep.append(match)
            break

    # Language split for English
    for name in apk_names:
        bn = Path(name).name.lower()
        if bn in ("config.en.apk", "config.en_us.apk"):
            keep.append(name)
            break

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in keep:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    return unique if unique else apk_names  # fallback: keep everything


# ---------------------------------------------------------------------------
# APKEditor merge
# ---------------------------------------------------------------------------

def _merge_with_apkeditor(splits_dir: Path, output_apk: Path) -> bool:
    """
    Run APKEditor's merge command on all APKs in splits_dir.
    Returns True on success.
    """
    _require_java()
    _require_jar(APKEDITOR_JAR, "APKEditor")

    print(f"[*] Merging splits with APKEditor…")
    cmd = [
        "java", "-jar", str(APKEDITOR_JAR),
        "m",
        "-i", str(splits_dir),
        "-o", str(output_apk),
        "-f",  # overwrite existing output
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.stdout:
        for line in result.stdout.splitlines():
            print(f"    {line}")
    if result.returncode != 0:
        print(f"[!] APKEditor error:\n{result.stderr}")
        return False

    if not output_apk.exists():
        print("[!] APKEditor finished but output file is missing.")
        return False

    size_mb = output_apk.stat().st_size / 1_048_576
    print(f"[+] Merged: {output_apk.name}  ({size_mb:.1f} MB)")
    return True


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def _convert_split_archive(
    archive: Path, output_dir: Path, arch: str
) -> Optional[Path]:
    """
    Shared logic for XAPK and APKM: extract relevant splits, merge with
    APKEditor.  Falls back to base.apk-only if merge fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        all_names = zf.namelist()

    apk_names = [n for n in all_names if n.endswith(".apk")]

    # Single-APK archive — just extract it
    if len(apk_names) == 1:
        print("[*] Single APK inside archive — extracting directly.")
        with zipfile.ZipFile(archive) as zf:
            data = zf.read(apk_names[0])
        out = output_dir / (archive.stem + ".apk")
        out.write_bytes(data)
        print(f"[+] Extracted: {out.name}")
        return out

    # Multi-split — select and merge
    selected = _select_splits(apk_names, arch)
    print(f"[*] Selected {len(selected)} split(s) from archive:")
    for name in selected:
        print(f"    {name}")

    splits_dir = output_dir / f".splits_{archive.stem}"
    splits_dir.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in selected:
                dest = splits_dir / Path(name).name
                dest.write_bytes(zf.read(name))

        output_apk = output_dir / (archive.stem + "_merged.apk")

        if not _merge_with_apkeditor(splits_dir, output_apk):
            # Fallback: use base.apk alone
            base = splits_dir / "base.apk"
            if base.exists():
                print("[!] Merge failed — falling back to base.apk only.")
                output_apk = output_dir / (archive.stem + "_base.apk")
                shutil.copy(str(base), str(output_apk))
                return output_apk
            return None

        return output_apk
    finally:
        if splits_dir.exists():
            shutil.rmtree(splits_dir)


def convert_xapk(path: Path, output_dir: Path, arch: str = DEFAULT_ARCH) -> Optional[Path]:
    """Convert an XAPK (or APKM) archive to a single merged APK."""
    return _convert_split_archive(path, output_dir, arch)


def convert_aab(path: Path, output_dir: Path, arch: str = DEFAULT_ARCH) -> Optional[Path]:
    """
    Convert an AAB (Android App Bundle) to a merged APK.

    Steps:
      1. bundletool generates a device-specific .apks archive (ZIP of splits).
      2. Splits are extracted and fed to APKEditor for merging.
    """
    _require_java()
    _require_jar(BUNDLETOOL_JAR, "bundletool")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Device spec targeting arm64, API 30, xxhdpi
    device_spec = {
        "supportedAbis": [arch, "armeabi-v7a"],
        "screenDensity": 420,
        "sdkVersion": 30,
        "supportedLocales": ["en-US"],
    }
    spec_file = output_dir / "_device_spec.json"
    spec_file.write_text(json.dumps(device_spec))

    apks_archive = output_dir / (path.stem + ".apks")

    print(f"[*] Running bundletool to build APK set…")
    cmd = [
        "java", "-jar", str(BUNDLETOOL_JAR),
        "build-apks",
        f"--bundle={path}",
        f"--output={apks_archive}",
        f"--device-spec={spec_file}",
        "--mode=default",
        "--overwrite",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    spec_file.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"[!] bundletool failed:\n{result.stderr}")
        return None

    # Extract .apks (it is just a ZIP)
    extract_dir = output_dir / f".apks_{path.stem}"
    extract_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(apks_archive) as zf:
        zf.extractall(extract_dir)
    apks_archive.unlink(missing_ok=True)

    # Collect all .apk files produced by bundletool
    splits_dir = output_dir / f".splits_{path.stem}"
    splits_dir.mkdir(exist_ok=True)
    for apk in extract_dir.rglob("*.apk"):
        shutil.copy(str(apk), str(splits_dir / apk.name))
    shutil.rmtree(extract_dir)

    output_apk = output_dir / (path.stem + "_merged.apk")
    try:
        if not _merge_with_apkeditor(splits_dir, output_apk):
            # Fallback to base-master.apk
            candidates = list(splits_dir.glob("base*.apk"))
            if candidates:
                print("[!] Merge failed — using base APK only.")
                output_apk = output_dir / (path.stem + "_base.apk")
                shutil.copy(str(candidates[0]), str(output_apk))
                return output_apk
            return None
        return output_apk
    finally:
        if splits_dir.exists():
            shutil.rmtree(splits_dir)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def convert(
    path: Path,
    output_dir: Optional[Path] = None,
    arch: str = DEFAULT_ARCH,
) -> Optional[Path]:
    """
    Auto-detect the format of `path` and convert to a clean APK.

    Returns the output Path on success, None on failure.
    """
    path = Path(path)
    if not path.exists():
        print(f"[!] File not found: {path}", file=sys.stderr)
        return None

    output_dir = Path(output_dir) if output_dir else (path.parent / "converted")
    output_dir.mkdir(parents=True, exist_ok=True)

    fmt = detect_format(path)
    print(f"[*] {path.name}  →  format: {fmt.upper()}")

    if fmt == "apk":
        dest = output_dir / path.name
        if dest.resolve() != path.resolve():
            shutil.copy(str(path), str(dest))
        print(f"[+] Plain APK — no conversion needed: {dest.name}")
        return dest

    if fmt in ("xapk", "apkm"):
        return convert_xapk(path, output_dir, arch)

    if fmt == "aab":
        return convert_aab(path, output_dir, arch)

    print(f"[!] Unsupported format '{fmt}' for: {path.name}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert XAPK / APKM / AAB packages to a plain APK for JADX",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s app.xapk
  %(prog)s app.apkm --output ./converted/
  %(prog)s app.aab  --arch armeabi-v7a
  %(prog)s ../downloads/ --batch          # convert every file in a directory
        """,
    )
    parser.add_argument(
        "input",
        help="Input file (.xapk / .apkm / .aab / .apk) or directory (with --batch)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="DIR",
        help="Output directory (default: <input_dir>/converted/)",
    )
    parser.add_argument(
        "--arch",
        default=DEFAULT_ARCH,
        help=f"Target ABI for split selection (default: {DEFAULT_ARCH})",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process every supported file in the input directory",
    )

    args = parser.parse_args()
    input_path = Path(args.input)
    out = Path(args.output) if args.output else None

    if args.batch or input_path.is_dir():
        if not input_path.is_dir():
            print("[!] --batch requires a directory as input.", file=sys.stderr)
            sys.exit(1)
        supported = {".xapk", ".apkm", ".aab", ".apk"}
        files = [f for f in input_path.iterdir() if f.suffix.lower() in supported]
        if not files:
            print(f"[!] No supported files found in {input_path}", file=sys.stderr)
            sys.exit(1)
        out_dir = out or (input_path / "converted")
        for f in sorted(files):
            print(f"\n{'=' * 60}")
            result = convert(f, out_dir, args.arch)
            status = f"[+] OK  → {result.name}" if result else "[-] FAILED"
            print(status)
    else:
        out_dir = out or (input_path.parent / "converted")
        result = convert(input_path, out_dir, args.arch)
        if not result:
            sys.exit(1)


if __name__ == "__main__":
    main()
