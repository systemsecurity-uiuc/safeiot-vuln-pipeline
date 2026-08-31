# UMCCI Checker — Security Analysis

Implements **Flaw Type 4 — Untrusted Fabric Information** from the NDSS 2025 paper
"Hidden and Lost Control: on Security Design Risks in IoT User-Facing Matter Controller."

Matter stores controller identity — Vendor ID and Label — inside each fabric entry on the
device. Those values are set by the controller itself and are never cryptographically
verified. Anything that can open a commissioning window can therefore join a device's
fabric under an arbitrary identity, and the owner's hub app will display whatever was
stored.

The analysis has two halves:

**Injecting a forged fabric.** `chip_tool_pair_forged()` pairs `chip-tool` with the
virtual device using **VID 4362** (SmartThings, confirmed in Table II of the paper), and
`chip_tool_set_label()` sets the fabric label to `"SmartThings Hub"`.
`chip_tool_open_commissioning_window()` then opens a window so the real controller can
join as well.

**Checking what the user is shown.** Two Claude agents drive the Google Home UI through
`mobile-mcp`: the first completes commissioning, the second navigates to the device's
linked-services screen and captures what identity is displayed. The tool reports whether
the forged Vendor ID and Label reach the user — if they do, the flaw is confirmed.

On a rerun with existing state in `storage/`, pairing is skipped and only the UI check
runs.

## Files

| File | Purpose |
|---|---|
| `umcci_checker.py` | The whole flow: environment checks, device build and launch, fabric injection, agent-driven verification, report |
| `requirements.txt` | Python dependencies |

## Running

Use the harness rather than calling this directly, so that the output lands in stage 4:

```bash
./pipeline_harness/umcci-checker/run.sh
```

The `CHIP_TOOL` environment variable selects which `chip-tool` build to use; the default at
the top of `umcci_checker.py` points at the original author's checkout.
