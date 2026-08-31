# Local Pipeline Deployment

How to run the pipeline on your own machine.

Each tool carries its own prerequisites; there is no single install step for the repository. The per-tool entry points live in
[`pipeline_harness/`](../pipeline_harness/): pick a tool, read its README, and run its
script.

| Tool | Harness |
|---|---|
| UMCCI Checker | [`pipeline_harness/umcci-checker/`](../pipeline_harness/umcci-checker/README.md) |

Shared analysis objects that several tools depend on — protocol specifications, the CHIP
SDK, the IoT companion-app crawler — are set up once under
[`1_analysis_object/general/`](../1_analysis_object/general/README.md).
