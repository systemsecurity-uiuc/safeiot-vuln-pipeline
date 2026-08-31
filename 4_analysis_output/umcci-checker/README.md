# UMCCI Checker — Analysis Output

A run prints a **Flaw Type 4 Test Report**: what the agent found on Google Home's
device-settings screen, and specifically whether the forged Vendor ID and Label injected
in [stage 3](../../3_security_analysis/umcci-checker/README.md) are displayed to the
user. Seeing the forged identity there confirms the flaw.

## Committed example

| File | What it is |
|---|---|
| `example_run.log` | A full run, from device build through the agent's verification report |
| `flaw4-forged-fabric-evidence.png` | Google Home showing "SmartThings Hub" as a linked service, when no SmartThings hub was ever involved |

The screenshot is the finding: Google Home presents attacker-chosen identity to the owner
with no indication that it is unverified.

Running through the harness also writes `last_run.log` here. That file is gitignored —
`example_run.log` is the version kept as the reference.
