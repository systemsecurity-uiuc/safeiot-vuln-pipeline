# Shared Analysis Objects

Analysis objects that are not tied to a single tool. Anything here is expected to be
useful to more than one tool in the pipeline, so it is maintained once and reused.

| Directory | Contents |
|---|---|
| [`specifications/`](specifications/) | IoT protocol specification documents, currently focused on Matter |
| [`chip-sdk/`](chip-sdk/) | Instructions and helper scripts for setting up the CHIP SDK, the Matter reference implementation |
| [`mobile_apps/`](mobile_apps/) | Crawler and curated list for collecting mainstream IoT companion apps to analyze |

If your tool needs an object that another tool could plausibly reuse, add it here rather
than under your own tool directory, and say in your tool's stage-1 README that you depend
on it.
