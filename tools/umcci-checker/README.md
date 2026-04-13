# UMCCI Checker

UMCCI Checker automatically identifies security vulnerabilities in IoT vendors' Matter SDK integrations. It has been adopted by CSA, Apple, Google, SmartThings, Comcast, and Tuya.

This demo implements **Flaw Type 4 — Untrusted Fabric Information**, based on the NDSS 2025 paper "Hidden and Lost Control: on Security Design Risks in IoT User-Facing Matter Controller."

## Overview

The checker pairs a virtual Matter device with Google Home, then injects a second fabric using chip-tool with a **forged Vendor ID** (impersonating SmartThings, VID=4362) and a **forged Label** ("SmartThings Hub"). An LLM agent then navigates the Google Home UI to verify whether the forged fabric information is displayed to the user — demonstrating that Matter's fabric metadata is entirely unverified.

## Prerequisites

- macOS host with Python 3.11+
- Android phone connected via ADB (`adb devices` must show a live device)
- Google Home app installed and signed in on the phone
- [matter.js](https://github.com/project-chip/matter.js) OnOff device built at `../matter-devices/device-onoff/`
- `chip-tool` built at `../../connectedhomeip/out/host/chip-tool`
- `claude_agent_sdk` Python package installed
- `mobile-mcp` MCP server configured in `~/.claude/settings.json`

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python3 umcci_checker.py
```

On **first run** (fresh storage):
1. Starts the matter.js virtual OnOff device.
2. chip-tool pairs with the device using forged VID=4362 and Label="SmartThings Hub".
3. Opens a commissioning window; a Claude agent navigates Google Home to complete pairing.
4. A second agent navigates Google Home's device settings to find and screenshot the fabric info.

On **subsequent runs** (storage reused):
- Skips pairing — existing fabrics (including the forged one) are already on the device.
- Goes directly to the Google Home UI verification step.

To start fresh, delete the `storage/` directory:
```bash
rm -rf storage/
```

## Output

The script prints a **Flaw Type 4 Test Report** describing what the agent found in Google Home's device settings — specifically whether the forged Vendor ID and Label are displayed.

## Flaw Type 4 — How It Works

The Matter protocol stores controller identity (Vendor ID, Label) inside each fabric entry on the device. These values are **set by the controller itself** and are never cryptographically verified. Any app or tool that can open a commissioning window can join a device's fabric with arbitrary VID/Label values, and the owner's hub app (Google Home) will display whatever is stored — potentially misleading the owner about which services have control of their device.
