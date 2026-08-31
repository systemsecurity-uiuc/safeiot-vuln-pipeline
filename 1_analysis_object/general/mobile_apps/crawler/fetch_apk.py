#!/usr/bin/env python3
"""
fetch_apk.py — Download Android APKs from APKPure.

Usage:
    python fetch_apk.py <package_name>
    python fetch_apk.py <package_name> --list-versions
    python fetch_apk.py <package_name> --version 7.6.0
    python fetch_apk.py --batch ../../iot_app_list.json

Downloads are saved to ../downloads/<package_name>/ by default.
Files are typically .xapk format (split-APK bundle); run convert_apk.py
to merge them into a single APK for JADX analysis.

APKPure page structure (verified 2025-04):
  - Versions page : /download/  links use the version name string (e.g. "7.6.0")
  - Download page : <a id="download_link"> or <a class="download-start-btn">
                    carries the direct CDN URL (d.apkpure.com) with
                    ?versionCode=NNN&nc=arm64-v8a&sv=24 already set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
DOWNLOADS_DIR = Path(__file__).parent.parent / "downloads"
APKPURE_BASE = "https://apkpure.com"
PREFERRED_ARCH = "arm64-v8a"   # appended to CDN URL if not already present

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------------------
# APKPure helpers
# ---------------------------------------------------------------------------

def find_app_url(session: requests.Session, package_name: str) -> Optional[str]:
    """
    Search APKPure for an app by package name and return its canonical page URL.

    APKPure search results contain <a href="/{slug}/{package_name}"> links.
    We scan all anchors for one whose last path segment matches the package name.
    """
    search_url = f"{APKPURE_BASE}/search?q={package_name}"
    try:
        resp = session.get(search_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Search request failed: {exc}", file=sys.stderr)
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    for a in soup.find_all("a", href=True):
        raw = a["href"].split("?")[0].rstrip("/")
        parts = raw.lstrip("/").split("/")
        # Accept both /{slug}/{pkg} and full https://apkpure.com/{slug}/{pkg}
        if len(parts) >= 2 and parts[-1] == package_name:
            # Rebuild a canonical absolute URL
            slug = parts[-2]
            return f"{APKPURE_BASE}/{slug}/{package_name}"

    return None


def get_version_list(session: requests.Session, app_url: str, limit: int = 20) -> list[dict]:
    """
    Fetch the APKPure versions page and return up to `limit` recent versions.

    APKPure versions page structure (verified 2025-04):
      - Each version entry is a row that includes:
          <div class="version-info-first-line">AppName\\n{version}</div>
          <div class="ver-item-info">{size} {date}</div>
      - Download links: <a href="/…/download/{version_name}"> where version_name
        is the human-readable string like "7.6.0", NOT a numeric code.
    """
    versions_url = f"{app_url}/versions"
    try:
        resp = session.get(versions_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Could not fetch versions page: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[dict] = []
    seen: set[str] = set()

    # Pair up version-info-first-line and ver-item-info divs
    name_divs = soup.find_all("div", class_="version-info-first-line")
    info_divs = soup.find_all("div", class_="ver-item-info")

    for name_div, info_div in zip(name_divs, info_divs):
        # version name is the last token after a newline / whitespace
        raw_name = name_div.get_text(" ", strip=True)
        # e.g. "Tuya 7.6.0" → take the last space-separated token
        version_name = raw_name.split()[-1] if raw_name else ""

        if not version_name or version_name in seen:
            continue
        seen.add(version_name)

        # info text: e.g. "193.9 MB Apr 8, 2026"
        info_text = info_div.get_text(" ", strip=True)
        # Extract date (anything that looks like a date)
        date_m = re.search(r"([A-Z][a-z]+ \d+, \d{4}|\d{4}-\d{2}-\d{2})", info_text)
        date = date_m.group(1) if date_m else info_text

        page_url = f"{app_url}/download/{version_name}"
        results.append(
            {
                "version_name": version_name,
                "date": date,
                "page_url": page_url,
            }
        )

        if len(results) >= limit:
            break

    # Fallback: scan <a> tags for /download/{version} if divs weren't found
    if not results:
        ver_re = re.compile(r"/download/([\d][^/?#\s]+)$")
        for a in soup.find_all("a", href=True):
            m = ver_re.search(a["href"])
            if not m:
                continue
            version_name = m.group(1)
            if version_name in seen:
                continue
            seen.add(version_name)
            results.append(
                {
                    "version_name": version_name,
                    "date": "",
                    "page_url": urljoin(APKPURE_BASE, a["href"].split("?")[0]),
                }
            )
            if len(results) >= limit:
                break

    return results


def extract_download_url(session: requests.Session, download_page_url: str) -> Optional[str]:
    """
    Retrieve the direct CDN file URL from an APKPure download page.

    APKPure download page patterns (verified 2025-04):
      1. <a id="download_link" href="https://d.apkpure.com/b/XAPK/...">
      2. <a class="btn download-start-btn" href="...">
      3. <a class="download-btn" href="https://d.apkpure.com/...">
      4. Fallback: scan <script> tags for a d.apkpure.com URL.
    """
    try:
        resp = session.get(download_page_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Could not fetch download page: {exc}", file=sys.stderr)
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Pattern 1: id="download_link" — most reliable
    tag = soup.find("a", id="download_link")
    if tag and tag.get("href", "").startswith("http"):
        return _ensure_arch(tag["href"])

    # Pattern 2: download-start-btn
    tag = soup.find("a", class_=re.compile(r"download-start-btn"))
    if tag and tag.get("href", "").startswith("http"):
        return _ensure_arch(tag["href"])

    # Pattern 3: any <a class="download-btn"> pointing to d.apkpure.com
    for tag in soup.find_all("a", class_=re.compile(r"download-btn")):
        href = tag.get("href", "")
        if "d.apkpure.com" in href:
            return _ensure_arch(href)

    # Pattern 4: body data-dt-apkid  →  construct CDN URL directly
    body = soup.find("body")
    if body:
        apkid = body.get("data-dt-apkid", "")
        if apkid:
            url = f"https://d.apkpure.com/{apkid}?nc={PREFERRED_ARCH}&sv=24"
            return url

    # Pattern 5: inline script scan
    cdn_re = re.compile(
        r'https://d\.apkpure\.com/[^\s"\']+\.(?:xapk|apkm|apk)[^\s"\']*', re.I
    )
    for script in soup.find_all("script"):
        txt = script.string or ""
        m = cdn_re.search(txt)
        if m:
            return _ensure_arch(m.group(0))

    return None


def _ensure_arch(url: str) -> str:
    """Make sure the CDN URL requests the arm64-v8a ABI variant."""
    if "nc=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}nc={PREFERRED_ARCH}&sv=24"
    return url


def download_file(
    session: requests.Session,
    url: str,
    dest_dir: Path,
    chunk_size: int = 1024 * 1024,
) -> Optional[Path]:
    """
    Stream-download a file to dest_dir.
    Filename comes from Content-Disposition; falls back to the URL path.
    Returns the saved Path on success, None on failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        resp = session.get(url, stream=True, timeout=120, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Download failed: {exc}", file=sys.stderr)
        return None

    # Determine filename
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename=["\']?([^"\';\r\n]+)', cd)
    if m:
        filename = m.group(1).strip()
    else:
        filename = url.split("?")[0].split("/")[-1] or "download.apk"

    dest = dest_dir / filename
    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0

    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                fh.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    bar = "#" * int(pct / 5)
                    print(
                        f"\r  [{bar:<20}] {pct:5.1f}%  "
                        f"{downloaded/1_048_576:.1f}/{total/1_048_576:.1f} MB",
                        end="",
                        flush=True,
                    )

    print()  # newline after progress bar
    return dest


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_apk(
    package_name: str,
    output_dir: Optional[Path] = None,
    version: Optional[str] = None,
    list_versions: bool = False,
) -> Optional[Path]:
    """
    Search APKPure, optionally list/filter versions, then download.

    Args:
        package_name:  Android package name, e.g. "com.tuya.smart"
        output_dir:    Save location (default: downloads/<package>/)
        version:       Version name to download, e.g. "7.6.0"; None = latest
        list_versions: If True, print available versions without downloading.

    Returns:
        Path to the downloaded file, or None on failure.
        When list_versions=True, returns the version list (list[dict]) instead.
    """
    output_dir = output_dir or (DOWNLOADS_DIR / package_name)
    session = make_session()

    print(f"[*] Searching APKPure for: {package_name}")
    app_url = find_app_url(session, package_name)
    if not app_url:
        print(f"[!] App not found on APKPure: {package_name}", file=sys.stderr)
        return None
    print(f"[+] Found: {app_url}")

    if list_versions:
        print("[*] Fetching version list (up to 20)…")
        versions = get_version_list(session, app_url)
        if not versions:
            print("[!] No versions found.")
            return None
        print(f"\n{'#':>4}  {'Version':<15}  Date")
        print("-" * 40)
        for i, v in enumerate(versions, 1):
            print(f"{i:>4}  {v['version_name']:<15}  {v['date']}")
        return versions  # type: ignore[return-value]

    # Build the download page URL
    if version:
        download_page = f"{app_url}/download/{version}"
    else:
        download_page = f"{app_url}/download"

    print(f"[*] Resolving download link from: {download_page}")
    time.sleep(1)
    dl_url = extract_download_url(session, download_page)
    if not dl_url:
        print(
            "[!] Could not extract a download URL.\n"
            "    APKPure may have changed their page structure.\n"
            f"    Check manually: {download_page}",
            file=sys.stderr,
        )
        return None

    short = dl_url[:90] + ("…" if len(dl_url) > 90 else "")
    print(f"[+] CDN URL: {short}")

    saved = download_file(session, dl_url, output_dir)
    if saved:
        size_mb = saved.stat().st_size / 1_048_576
        print(f"[+] Saved: {saved}  ({size_mb:.1f} MB)")
    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Android APKs from APKPure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s com.tuya.smart
  %(prog)s com.tuya.smart --list-versions
  %(prog)s com.tuya.smart --version 7.6.0
  %(prog)s --batch ../../iot_app_list.json
  %(prog)s com.google.android.apps.chromecast.app -o /tmp/apks/
        """,
    )
    parser.add_argument("package", nargs="?", help="Android package name")
    parser.add_argument(
        "--list-versions",
        action="store_true",
        help="Print available versions (up to 20) without downloading",
    )
    parser.add_argument(
        "--version",
        metavar="VERSION",
        help="Version name to download, e.g. '7.6.0' (default: latest)",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="DIR",
        help="Output directory (default: ../downloads/<package>/)",
    )
    parser.add_argument(
        "--batch",
        metavar="JSON_FILE",
        help="Download all apps listed in an iot_app_list.json file",
    )

    args = parser.parse_args()

    if args.batch:
        batch_path = Path(args.batch)
        if not batch_path.exists():
            print(f"[!] File not found: {batch_path}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(batch_path.read_text())
        packages = [app["package_name"] for app in data.get("apps", [])]
        if not packages:
            print("[!] No apps found in the JSON file.", file=sys.stderr)
            sys.exit(1)
        out_root = Path(args.output) if args.output else DOWNLOADS_DIR
        for pkg in packages:
            print(f"\n{'=' * 60}")
            print(f"  {pkg}")
            print("=" * 60)
            fetch_apk(pkg, output_dir=out_root / pkg)
            time.sleep(2)
    elif args.package:
        out = Path(args.output) if args.output else None
        result = fetch_apk(
            args.package,
            output_dir=out,
            version=args.version,
            list_versions=args.list_versions,
        )
        if result is None:
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
