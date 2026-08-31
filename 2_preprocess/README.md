# Stage 2 — Preprocess

Everything that turns a raw analysis object into something the security analysis can run
against: unpacking firmware, decompiling or converting an app, normalizing a
specification, building an emulation target, standing up a test environment.

Each tool gets a subdirectory named after the tool.

```
2_preprocess/
└── <tool-name>/
```

Not every tool needs this stage. If yours does not, add a short README in your tool's
directory saying so and why.
