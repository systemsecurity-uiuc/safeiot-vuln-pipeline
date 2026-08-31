# UMCCI Checker — Pipeline Harness

UMCCI Checker automatically identifies security vulnerabilities in IoT vendors' Matter
SDK integrations. The flaws it found have been fixed by CSA, Apple, Google, SmartThings,
Comcast, and Tuya. This demo implements **Flaw Type 4 — Untrusted Fabric Information**,
based on the NDSS 2025 paper "Hidden and Lost Control: on Security Design Risks in IoT
User-Facing Matter Controller."

The checker pairs a virtual Matter device with Google Home, joins a second fabric using
`chip-tool` with a forged Vendor ID (impersonating SmartThings, VID 4362) and a forged
Label ("SmartThings Hub"), then has an LLM agent navigate the Google Home UI to see
whether that forged identity is shown to the user — demonstrating that Matter's fabric
metadata is entirely unverified.

## Flow

| Stage | What happens |
|---|---|
| [1 — Analysis object](../../1_analysis_object/umcci-checker/README.md) | A live deployment: virtual Matter device, Google Home on a physical Android phone, `chip-tool` as a second controller |
| [2 — Preprocess](../../2_preprocess/umcci-checker/README.md) | Environment checks, then generating, building, and starting the virtual device |
| [3 — Security analysis](../../3_security_analysis/umcci-checker/README.md) | Joining the fabric with forged identity, then agent-driven verification of the Google Home UI |
| [4 — Analysis output](../../4_analysis_output/umcci-checker/README.md) | Flaw Type 4 test report and a screenshot of the forged fabric as displayed |

Stages 2 and 3 run inside the same process: the virtual device has to stay up for the
analysis to attach to it, so `run.sh` drives them as one invocation of
`umcci_checker.py` rather than as separate steps.

## Prerequisites

- macOS host with Python 3.11+
- Node.js and npm — the virtual Matter device is built automatically on first run
- Android phone connected over ADB (`adb devices` must show a live device), with Google
  Home installed and signed in
- `chip-tool` built from the CHIP SDK; point the `CHIP_TOOL` environment variable at your
  build
- `claude_agent_sdk` installed and the `mobile-mcp` MCP server configured in
  `~/.claude/settings.json`

## Running

From the repository root:

```bash
CHIP_TOOL=/path/to/connectedhomeip/out/host/chip-tool \
  ./pipeline_harness/umcci-checker/run.sh
```

This installs the Python dependencies, runs the checker, and writes the console output to
`4_analysis_output/umcci-checker/last_run.log`.

**First run** builds the virtual device, pairs it with forged fabric information, has an
agent complete commissioning in Google Home, and has a second agent capture what the
device-settings screen displays.

**Later runs** reuse the commissioned state in
`3_security_analysis/umcci-checker/storage/` and skip straight to the UI check. To start
over from a fresh device:

```bash
rm -rf 3_security_analysis/umcci-checker/storage/
```

## Why the flaw works

Matter stores controller identity — Vendor ID and Label — inside each fabric entry on the
device. Those values are set by the controller itself and are never cryptographically
verified. Any app or tool that can open a commissioning window can join a device's fabric
with arbitrary values, and the owner's hub app will display whatever is stored,
potentially misleading the owner about which services control their device.
