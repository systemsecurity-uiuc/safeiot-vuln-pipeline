# UMCCI Checker — Preprocess

Preprocessing brings up the live Matter deployment described in
[stage 1](../../1_analysis_object/umcci-checker/README.md). It is driven from `umcci_checker.py` in
[stage 3](../../3_security_analysis/umcci-checker/README.md): the virtual device has to stay
running for the analysis to attach to it.

Two steps run before any analysis:

**Environment checks** (`check_environment()`) — verifies that `chip-tool` is built at
the configured path, that `adb devices` reports a live phone, and that the Python
dependencies are importable. The run stops here rather than failing halfway through
commissioning.

**Building the virtual device** (`_ensure_matter_device()`) — on first run, writes
`package.json`, `tsconfig.json`, and the matter.js device source into `matter-device/`,
runs `npm install`, and compiles the TypeScript. Later runs reuse the build. The
directory is gitignored; deleting it forces a rebuild.

The device is then started on port 5542 (`start_matter_device()`) and left running for
the duration of the analysis.

## Prerequisites

- macOS host with Python 3.11+
- Node.js and npm
- Android phone connected over ADB, with Google Home installed and signed in
- `chip-tool` built from the CHIP SDK — see
  [`../../1_analysis_object/general/chip-sdk/`](../../1_analysis_object/general/chip-sdk/README.md)
- `claude_agent_sdk` installed and the `mobile-mcp` MCP server configured

The end-to-end command that runs this stage together with the rest is in
[`pipeline_harness/umcci-checker/`](../../pipeline_harness/umcci-checker/README.md).
