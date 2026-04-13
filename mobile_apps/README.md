# Mobile Apps

This directory contains data and tooling for collecting and analyzing mainstream IoT mobile applications, in support of cybersecurity label verification (see [Lalaine](https://github.com/safeiot)).

## Structure

```
mobile_apps/
├── crawler/     # Python scripts for app collection and metadata parsing
└── data/        # Collected app metadata and analysis outputs (gitignored by default)
```

## Data Collection

App data is collected automatically via a scheduled GitHub Actions workflow that runs the crawler scripts on a regular basis. See [crawler/README.md](crawler/README.md) for details on the scripts and how to run them locally.

## Data

Raw and processed data lives in `data/`. Large datasets are excluded from version control via `.gitignore`. Sample files or data schemas will be documented here as the pipeline matures.
