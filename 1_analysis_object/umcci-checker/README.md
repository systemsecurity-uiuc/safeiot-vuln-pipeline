# UMCCI Checker — Analysis Object

The object under analysis is not a file in this repository. It is a **live Matter
deployment** assembled at run time from three parts:

1. **A virtual Matter device** — a matter.js OnOff device that the tool generates and
   builds during [stage 2](../../2_preprocess/umcci-checker/README.md). The generated
   sources land in `3_security_analysis/umcci-checker/matter-device/` and are not
   tracked in git.
2. **Google Home on a physical Android phone** — the user-facing Matter controller whose
   behavior is being checked. Reached over ADB and driven through the `mobile-mcp` server.
3. **`chip-tool` from the CHIP SDK** — used as a second controller to join the device's
   fabric. See [`../general/chip-sdk/`](../general/chip-sdk/README.md) for setup.

Nothing static is checked in because the object only exists while the tool is running.
The commissioned state persists between runs in
`3_security_analysis/umcci-checker/storage/` (gitignored); deleting that directory
resets the deployment to a fresh device.

The behavior being checked comes from the Matter specification's treatment of fabric
metadata — see [`../general/specifications/`](../general/specifications/README.md).
