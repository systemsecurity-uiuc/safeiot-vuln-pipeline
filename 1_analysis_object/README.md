# Stage 1 — Analysis Object

What a tool analyzes: the firmware image, mobile app, source repository, specification
document, network capture, or live device that the rest of the pipeline operates on.

Each tool gets a subdirectory named after the tool. Objects that more than one tool can
reuse live in [`general/`](general/) instead of being duplicated per tool.

```
1_analysis_object/
├── general/          # Objects shared across tools
└── <tool-name>/      # Objects specific to one tool
```

Large binaries should not be committed. Provide a fetch script, a manifest, or
instructions for obtaining the object, and keep the downloads out of git.

If a tool has no analysis object that can be checked in — for example when the object is
a live device — describe what the object actually is and how it comes into existence.
