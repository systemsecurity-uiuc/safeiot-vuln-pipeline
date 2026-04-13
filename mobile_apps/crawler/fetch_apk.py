#!/usr/bin/env python3
"""
fetch_apk.py — Download Android APKs from APKPure.

Usage:
    python fetch_apk.py <package_name>
    python fetch_apk.py <package_name> --list-versions
    python fetch_apk.py <package_name> --version <version_code>
    python fetch_apk.py --batch ../../iot_app_list.json

Downloads are saved to ../downloads/<package_name>/ by default.
Files may be .apk or .xapk format; run convert_apk.py for post-processing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DOWNLOADS_DIR = Path(__file__).parent.parent / "downloads"

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------
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

APKPURE_BASE = "https://apkpure.com"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------------------
# APKPure helpers
# ---------------------------------------------------------------------------

def find_app_url(session: requests.Session, package_name: str) -> Optional[str]:
    """
    Search APKPure for an app by package name and return its page URL.

    APKPure page URLs follow the pattern:
        https://apkpure.com/{slug}/{package_name}
    where {slug} is derived from the display name (e.g. "tuya-smart").
    We obtain it by parsing the search results page.
    """
    search_url = f"{APKPURE_BASE}/search?q={package_name}"
    try:
        resp = session.get(search_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Search request failed: {exc}", file=sys.stderr)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Search result cards contain links of the form /{slug}/{package_name}
    for a in soup.find_all("a", href=True):
        href: str = a["href"].split("?")[0].rstrip("/")
        parts = href.lstrip("/").split("/")
        if len(parts) == 2 and parts[1] == package_name:
            return f"{APKPURE_BASE}/{parts[0]}/{parts[1]}"

    # Fallback: look for any href that ends with the package name
    for a in soup.find_all("a", href=True):
        if a["href"].endswith(f"/{package_name}"):
            href = a["href"].split("?")[0]
            return urljoin(APKPURE_BASE, href)

    return None


def get_version_list(session: requests.Session, app_url: str, limit: int = 20) -> list[dict]:
    """
    Fetch the APKPure version history page and return up to `limit` versions.

    Each entry is a dict with keys: version_name, version_code, date, page_url.
    """
    versions_url = f"{app_url}/versions"
    try:
        resp = session.get(versions_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Could not fetch versions page: {exc}", file=sys.stderr)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict] = []

    # Version list items contain links with /download/{version_code} in href
    for a in soup.find_all("a", href=True):
        m = re.search(r"/download/(\d+)", a["href"])
        if not m:
            continue
        version_code = m.group(1)

        # Avoid duplicates
        if any(v["version_code"] == version_code for v in results):
            continue

        # Try to pick up version name and date from nearby text
        container = a.find_parent(["li", "div", "tr"]) or a
        text = container.get_text(" ", strip=True)

        version_name = ""
        date = ""
        # Common pattern: "5.12.0 (123456789) 2024-01-15"
        ver_m = re.search(r"(\d+\.\d+[\d.]*)", text)
        if ver_m:
            version_name = ver_m.group(1)
        date_m = re.search(r"(\d{4}-\d{2}-\d{2}|\w+ \d+, \d{4})", text)
        if date_m:
            date = date_m.group(1)

        page_url = urljoin(APKPURE_BASE, a["href"].split("?")[0])
        results.append(
            {
                "version_name": version_name,
                "version_code": version_code,
                "date": date,
                "page_url": page_url,
            }
        )

        if len(results) >= limit:
            break

    return results


def extract_download_url(session: requests.Session, download_page_url: str) -> Optional[str]:
    """
    Retrieve the direct file download URL from an APKPure download page.

    APKPure places the actual download link in various locations depending on
    the app version: a data attribute, a <meta> refresh, or a script variable.
    We try each known pattern in turn.
    """
    try:
        resp = session.get(download_page_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[!] Could not fetch download page: {exc}", file=sys.stderr)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Pattern 1: <a id="download_link" href="...">
    tag = soup.find("a", id="download_link")
    if tag and tag.get("href"):
        return tag["href"]

    # Pattern 2: data-dt-url attribute on any element
    tag = soup.find(attrs={"data-dt-url": True})
    if tag:
        return tag["data-dt-url"]

    # Pattern 3: <a class="download-btn ..."> or "fast-download-btn"
    for cls_pat in ("download-btn", "fast-download-btn", "da"):
        tag = soup.find("a", class_=re.compile(cls_pat))
        if tag and tag.get("href") and tag["href"].startswith("http"):
            return tag["href"]

    # Pattern 4: meta http-equiv="refresh" (some pages redirect to CDN)
    meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
    if meta and meta.get("content"):
        m = re.search(r"url=(.+)", meta["content"], re.I)
        if m:
            return m.group(1).strip().strip("'\"")

    # Pattern 5: scan inline <script> for a CDN URL
    cdn_re = re.compile(
        r'https://[^\s"\']+\.(xapk|apkm|apk)(\?[^\s"\']*)?', re.I
    )
    for script in soup.find_all("script"):
        text = script.string or ""
        m = cdn_re.search(text)
        if m:
            return m.group(0)

    return None


def download_file(
    session: requests.Session,
    url: str,
    dest_dir: Path,
    chunk_size: int = 1024 * 1024,
) -> Optional[Path]:
    """
    Stream-download a file to dest_dir.
    Filename is taken from Content-Disposition, falling back to the URL path.
    Returns the saved Path on success, None on failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        resp = session.get(url, stream=True, timeout=60, allow_redirects=True)
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
                        f"\r  [{bar:<20}] {pct:5.1f}%  {downloaded/1_048_576:.1f} MB",
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
    version_code: Optional[str] = None,
    list_versions: bool = False,
) -> Optional[Path]:
    """
    Main entry point: search, (optionally list versions), and download.

    Args:
        package_name:  Android package name, e.g. "com.tuya.smart"
        output_dir:    Where to save the file (default: downloads/<package>/)
        version_code:  Specific APKPure version code; None = latest
        list_versions: If True, print available versions and return them
                       without downloading.

    Returns:
        Path to the downloaded file, or None on failure.
        When list_versions=True, returns the list of version dicts instead.
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
        print(f"[*] Fetching version list (up to 20)…")
        versions = get_version_list(session, app_url)
        if not versions:
            print("[!] No versions found.")
            return None
        print(f"\n{'#':>4}  {'Version':<20}  {'Code':<12}  Date")
        print("-" * 55)
        for i, v in enumerate(versions, 1):
            print(f"{i:>4}  {v['version_name']:<20}  {v['version_code']:<12}  {v['date']}")
        return versions  # type: ignore[return-value]

    # Construct the download page URL
    if version_code:
        download_page = f"{app_url}/download/{version_code}"
    else:
        download_page = f"{app_url}/download"

    print(f"[*] Resolving download link from: {download_page}")
    time.sleep(1)  # be polite to the server
    dl_url = extract_download_url(session, download_page)
    if not dl_url:
        print("[!] Could not extract a download URL.", file=sys.stderr)
        print(
            "    APKPure may have changed their page structure. "
            "Check the URL manually:\n   ",
            download_page,
            file=sys.stderr,
        )
        return None

    print(f"[+] Downloading from: {dl_url[:90]}{'…' if len(dl_url) > 90 else ''}")
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
  %(prog)s com.tuya.smart --version 123456789
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
        metavar="VERSION_CODE",
        help="APKPure version code to download (default: latest)",
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
            time.sleep(2)  # rate-limit between requests
    elif args.package:
        out = Path(args.output) if args.output else None
        result = fetch_apk(
            args.package,
            output_dir=out,
            version_code=args.version,
            list_versions=args.list_versions,
        )
        if result is None:
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
