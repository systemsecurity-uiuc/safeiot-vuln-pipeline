# SafeIoT Pipeline

A research data and tooling repository for the **SafeIoT Center** — the NSF-funded Center for Security and Privacy Assurance and Conformance in IoT Standards and Systems.

This repository collects and organizes IoT ecosystem research artifacts, with an initial focus on the **Matter** protocol and **FCC IoT Cybersecurity Labeling**. It is designed to be cloned locally and run after environment setup.

---

## Repository Structure

```
safeiot-pipeline/
├── specifications/          # IoT protocol specification documents 
├── chip-sdk/                # CHIP SDK setup instructions and helper scripts
├── mobile_apps/             # Mainstream IoT app data collection and analysis
├── tools/                   # Security verification tools integrated into the pipeline
│   └── umcci-checker/       #   UMCCI Checker (example; more tools to be added)
└── docs/
    └── local-deployment.md  # End-to-end guide for deploying the pipeline locally
```

---

## Getting Started

### Prerequisites

- Python 3.9+
- Git

### Clone and Setup

```bash
git clone https://github.com/systemsecurity-uiuc/safeiot-pipeline.git
cd safeiot-pipeline
pip install -r requirements.txt
```

---

## About SafeIoT

SafeIoT is a non-profit, community-driven open-source ecosystem providing CI/CD infrastructure that continuously verifies IoT standards and their implementations. Learn more at the [SafeIoT website]().

<!-- **Contact:** Luyi Xing — lxing2@illinois.edu, Associate Professor of CS, UIUC -->
