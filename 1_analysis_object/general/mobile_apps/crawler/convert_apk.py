#!/usr/bin/env python3
"""
convert_apk.py — Convert downloaded APK packages to JADX-ready plain APK.

Supported input formats
-----------------------
  .apk   Already a plain APK — copied to output directory as-is.
  .xapk  APKPure split-APK bundle (ZIP containing split APKs + manifest.json).
  .apkm  APKMirror split-APK bundle (same ZIP layout as XAPK).
  .aab   Android App Bundle — converted via bundletool, then splits merged.

Split selection strategy (for XAPK / APKM)
-------------------------------------------
APKPure XAPKs contain several kinds of APK inside the archive:

  1. Main APK  — named "base.apk" OR "{package_name}.apk".
                 Always included.  This carries all DEX (Java/Kotlin) code.
  2. Feature / asset splits — names like "switchbot_assets.apk", "feature_xyz.apk".
                 Always included.  May contain additional DEX or important resources.
  3. ABI config — "config.arm64_v8a.apk", "config.armeabi_v7a.apk", …
                 Include only the requested arch (default: arm64-v8a).
  4. Density config — "config.xxhdpi.apk", "config.xhdpi.apk", …
                 Include the highest available density.
  5. Language config — "config.en.apk", "config.zh.apk", …
                 Include only English (config.en.apk / config.en_us.apk).
  6. Skip — density configs for lower densities, other language configs,
              other-arch ABI configs.

APKEditor merge
---------------
All selected splits are placed in a temporary directory and fed to APKEditor's
"m" (merge) command, which produces a single installable APK.  If merge fails,
the script falls back to the main APK only (still usable in JADX).

External tool requirements
--------------------------
Place the following JARs in the tools/ subdirectory next to this script:
  tools/APKEditor.jar   — https://github.com/REAndroid/APKEditor/releases
  tools/bundletool.jar  — https://github.com/google/bundletool/releases (.aab only)
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
import re
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

# All known ABI tokens as they appear in split filenames
_ABI_TOKENS: dict[str, list[str]] = {
    "arm64-v8a":    ["arm64_v8a", "arm64-v8a"],
    "armeabi-v7a":  ["armeabi_v7a", "armeabi-v7a"],
    "x86_64":       ["x86_64"],
    "x86":          ["x86"],
}

# Screen densities in descending quality — we keep the first match
_DENSITY_PREF = ["xxxhdpi", "xxhdpi", "xhdpi", "hdpi", "tvdpi", "mdpi"]
# Densities we actively skip unless nothing better is available
_DENSITY_SKIP = {"ldpi", "nodpi", "tvdpi", "mdpi", "hdpi"}


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

def _check_java() -> bool:
    try:
        r = subprocess.run(["java", "-version"], capture_output=True, timeout=10)
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
    """Return one of: 'apk', 'xapk', 'apkm', 'aab', 'unknown'."""
    ext = path.suffix.lower()
    if ext in (".xapk", ".apkm", ".aab"):
        return ext[1:]

    if ext == ".apk":
        if not zipfile.is_zipfile(path):
            return "apk"
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        if "AndroidManifest.xml" in names:
            return "apk"
        if any(n.endswith(".apk") for n in names):
            return "xapk"  # mislabelled split-APK bundle

    return "unknown"


# ---------------------------------------------------------------------------
# Split classification
# ---------------------------------------------------------------------------

def _is_config_split(name: str) -> bool:
    """Return True if the filename looks like a config (not a main/feature APK)."""
    bn = Path(name).name.lower()
    return bn.startswith("config.")


def _classify_splits(apk_names: list[str], arch: str) -> dict[str, list[str]]:
    """
    Classify APK entries in an archive into categories:
      main     — base.apk or {package}.apk (not a config split)
      feature  — non-config splits that are also not the main APK
                 (e.g. switchbot_assets.apk, feature_xyz.apk)
      arch     — config.{arch}.apk for the requested ABI
      density  — config.{density}.apk
      language — config.{lang}.apk
      other    — anything else (typically skipped)
    """
    arch_tokens = _ABI_TOKENS.get(arch, [arch.replace("-", "_")])
    other_arch_tokens: list[str] = [
        t
        for a, tokens in _ABI_TOKENS.items()
        if a != arch
        for t in tokens
    ]

    categories: dict[str, list[str]] = {
        "main": [], "feature": [], "arch": [],
        "density": [], "language": [], "other": [],
    }

    for name in apk_names:
        bn = Path(name).name.lower()
        if not bn.endswith(".apk"):
            continue

        if not _is_config_split(bn):
            # Main APK: base.apk or {pkg}.apk
            # Feature/asset APK: anything else (e.g. switchbot_assets.apk)
            if bn == "base.apk":
                categories["main"].append(name)
            else:
                # Heuristic: if it's the largest non-config APK it's probably main
                # We collect all non-config splits; main will be identified by size later
                categories["feature"].append(name)
        else:
            # It's a config split — determine sub-type
            inner = bn[len("config."):]  # strip "config." prefix

            if any(t in inner for t in arch_tokens):
                categories["arch"].append(name)
            elif any(t in inner for t in other_arch_tokens):
                categories["other"].append(name)  # wrong ABI — skip
            elif any(d in inner for d in [d + ".apk" for d in _DENSITY_PREF]):
                categories["density"].append(name)
            elif re.match(r"[a-z]{2}(_[a-z]{2})?\.apk$", inner):
                categories["language"].append(name)
            else:
                categories["other"].append(name)

    return categories


def _select_splits(apk_names: list[str], arch: str) -> list[str]:
    """
    Given APK filenames inside an XAPK/APKM archive, return the optimal
    subset to feed to APKEditor for a complete, analysis-ready merge.

    Selection rules:
      - Main APK:   always included (base.apk or the largest non-config APK)
      - Feature splits: always included (they carry additional DEX / assets)
      - ABI config: include the requested arch; if missing, include armeabi-v7a
      - Density:    include the highest available density (first match in _DENSITY_PREF)
      - Language:   include config.en.apk or config.en_us.apk if present
      - Everything else: skip
    """
    cats = _classify_splits(apk_names, arch)

    keep: list[str] = []

    # ── Main APK ──────────────────────────────────────────────────────────
    if cats["main"]:
        keep.extend(cats["main"])
    elif cats["feature"]:
        # No base.apk found: treat the largest non-config APK as the main APK
        # and the rest as feature splits
        sorted_feats = sorted(cats["feature"], key=lambda n: Path(n).name)
        # We can't measure file sizes here (just filenames), so keep them all;
        # APKEditor will figure out which is the base
        keep.extend(cats["feature"])
        cats["feature"] = []  # already added

    # ── Feature / asset splits ────────────────────────────────────────────
    keep.extend(cats["feature"])

    # ── ABI config ───────────────────────────────────────────────────────
    if cats["arch"]:
        keep.extend(cats["arch"])
    else:
        # Fallback: look for armeabi-v7a config (universal fallback)
        fallback_tokens = _ABI_TOKENS.get("armeabi-v7a", [])
        for name in apk_names:
            bn = Path(name).name.lower()
            if _is_config_split(bn) and any(t in bn for t in fallback_tokens):
                print(f"    [note] No arm64 config found, using armeabi-v7a config: {Path(name).name}")
                keep.append(name)
                break

    # ── Density config ───────────────────────────────────────────────────
    density_added = False
    for density in _DENSITY_PREF:
        for name in cats["density"]:
            if density in Path(name).name.lower():
                keep.append(name)
                density_added = True
                break
        if density_added:
            break

    # ── Language config ──────────────────────────────────────────────────
    for name in cats["language"]:
        bn = Path(name).name.lower()
        if bn in ("config.en.apk", "config.en_us.apk"):
            keep.append(name)
            break

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in keep:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    return unique


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

    print(f"[*] Merging with APKEditor…  ({len(list(splits_dir.glob('*.apk')))} splits)")
    cmd = [
        "java", "-jar", str(APKEDITOR_JAR),
        "m",
        "-i", str(splits_dir),
        "-o", str(output_apk),
        "-f",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Print relevant output lines only
    for line in (result.stdout + result.stderr).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("##"):  # skip decorative lines
            print(f"    {stripped}")

    if result.returncode != 0:
        return False

    if not output_apk.exists():
        print("[!] APKEditor finished but output file is missing.")
        return False

    size_mb = output_apk.stat().st_size / 1_048_576
    print(f"[+] Merged APK: {output_apk.name}  ({size_mb:.1f} MB)")
    return True


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def _convert_split_archive(
    archive: Path, output_dir: Path, arch: str
) -> Optional[Path]:
    """Shared logic for XAPK and APKM archives."""
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        all_names = zf.namelist()

    apk_names = [n for n in all_names if n.endswith(".apk")]
    if not apk_names:
        print(f"[!] No APK files found inside {archive.name}")
        return None

    # Single-APK archive — extract directly, no merge needed
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

    print(f"[*] Split selection ({len(selected)}/{len(apk_names)} files from archive):")
    for name in selected:
        # Look up size from archive
        info = next((i for i in zf.infolist() if i.filename == name), None) \
            if False else None  # size lookup below
        print(f"    + {name}")

    skipped = [n for n in apk_names if n not in selected]
    for name in skipped:
        print(f"    - {name}  (skipped)")

    splits_dir = output_dir / f".splits_{archive.stem}"
    splits_dir.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in selected:
                dest = splits_dir / Path(name).name
                dest.write_bytes(zf.read(name))

        output_apk = output_dir / (archive.stem + "_merged.apk")

        if not _merge_with_apkeditor(splits_dir, output_apk):
            # Fallback: find main APK (base.apk or largest non-config APK)
            main_apk = _find_main_apk(splits_dir)
            if main_apk:
                print(f"[!] Merge failed — falling back to main APK only: {main_apk.name}")
                output_apk = output_dir / (archive.stem + "_base.apk")
                shutil.copy(str(main_apk), str(output_apk))
                return output_apk
            return None

        return output_apk
    finally:
        if splits_dir.exists():
            shutil.rmtree(splits_dir)


def _find_main_apk(apk_dir: Path) -> Optional[Path]:
    """
    Find the main APK in a directory: prefer base.apk, otherwise the largest
    non-config APK file.
    """
    base = apk_dir / "base.apk"
    if base.exists():
        return base
    # Largest non-config APK
    candidates = [f for f in apk_dir.glob("*.apk") if not f.name.lower().startswith("config.")]
    if candidates:
        return max(candidates, key=lambda f: f.stat().st_size)
    # Last resort: largest APK of any kind
    all_apks = list(apk_dir.glob("*.apk"))
    if all_apks:
        return max(all_apks, key=lambda f: f.stat().st_size)
    return None


def convert_xapk(path: Path, output_dir: Path, arch: str = DEFAULT_ARCH) -> Optional[Path]:
    """Convert an XAPK or APKM archive to a single merged APK."""
    return _convert_split_archive(path, output_dir, arch)


def convert_aab(path: Path, output_dir: Path, arch: str = DEFAULT_ARCH) -> Optional[Path]:
    """
    Convert an AAB (Android App Bundle) to a merged APK.
    Steps: bundletool → device-specific .apks → extract → APKEditor merge.
    """
    _require_java()
    _require_jar(BUNDLETOOL_JAR, "bundletool")

    output_dir.mkdir(parents=True, exist_ok=True)

    device_spec = {
        "supportedAbis": [arch, "armeabi-v7a"],
        "screenDensity": 420,
        "sdkVersion": 30,
        "supportedLocales": ["en-US"],
    }
    spec_file = output_dir / "_device_spec.json"
    spec_file.write_text(json.dumps(device_spec))

    apks_archive = output_dir / (path.stem + ".apks")

    print("[*] Running bundletool to build device-specific APK set…")
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

    extract_dir = output_dir / f".apks_{path.stem}"
    extract_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(apks_archive) as zf:
        zf.extractall(extract_dir)
    apks_archive.unlink(missing_ok=True)

    splits_dir = output_dir / f".splits_{path.stem}"
    splits_dir.mkdir(exist_ok=True)
    for apk in extract_dir.rglob("*.apk"):
        shutil.copy(str(apk), str(splits_dir / apk.name))
    shutil.rmtree(extract_dir)

    output_apk = output_dir / (path.stem + "_merged.apk")
    try:
        if not _merge_with_apkeditor(splits_dir, output_apk):
            main_apk = _find_main_apk(splits_dir)
            if main_apk:
                print(f"[!] Merge failed — using: {main_apk.name}")
                output_apk = output_dir / (path.stem + "_base.apk")
                shutil.copy(str(main_apk), str(output_apk))
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
    """Auto-detect format and convert to a clean APK. Returns output Path."""
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
    parser.add_argument("--output", "-o", metavar="DIR", help="Output directory")
    parser.add_argument(
        "--arch", default=DEFAULT_ARCH,
        help=f"Target ABI for split selection (default: {DEFAULT_ARCH})",
    )
    parser.add_argument(
        "--batch", action="store_true",
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
            print(f"[+] OK  → {result.name}" if result else "[-] FAILED")
    else:
        out_dir = out or (input_path.parent / "converted")
        result = convert(input_path, out_dir, args.arch)
        if not result:
            sys.exit(1)


if __name__ == "__main__":
    main()
