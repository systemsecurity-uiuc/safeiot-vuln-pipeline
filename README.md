# SafeIoT Pipeline

Part of the **[SafeIoT Center](https://safe-iot.com/)** — the NSF-funded Center for Security and Privacy Assurance and Conformance in IoT Standards and Systems (supported by NSF, UIUC, UNC Charlotte, and Indiana University).

Consumers increasingly rely on IoT products for home safety, health, and everyday convenience, yet popular IoT standards and their implementations lack holistic, rigorous security and privacy verification. SafeIoT addresses this gap with a community-driven, open-source CI/CD infrastructure that continuously verifies IoT standards and vendor implementations, with an initial focus on the **Matter** standard and **SBOM** in the IoT context.

The SafeIoT pipeline is organized into two complementary tracks, each with its own repository:

| Track | Repository | Focus | Example Tool |
|---|---|---|---|
| 1 — IoT Vulnerability Detection | **safeiot-vuln-pipeline** (this repo) | Vulnerabilities in IoT standards and their implementations, incl. commodity products such as Google Home, Apple Home, and SmartThings | [UMCCI Checker](tools/umcci-checker/) |
| 2 — IoT SBOM, CBOM, and AI-BOM Verification | [safeiot-supply-chain-pipeline](https://github.com/systemsecurity-uiuc/safeiot-supply-chain-pipeline) | Supply-chain security, privacy, and compliance issues in Software/Cryptographic/AI Bills of Materials for IoT systems | [JBomAudit](https://github.com/systemsecurity-uiuc/safeiot-supply-chain-pipeline/tree/main/tools/jbomaudit) |

---

## This Repository — Track 1: IoT Vulnerability Detection

This repository collects and organizes IoT ecosystem research artifacts for vulnerability detection, with an initial focus on the **Matter** protocol and **FCC IoT Cybersecurity Labeling**. It is designed to be cloned locally and run after environment setup.

## Repository Structure

```
safeiot-vuln-pipeline/
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
git clone https://github.com/systemsecurity-uiuc/safeiot-vuln-pipeline.git
cd safeiot-vuln-pipeline
pip install -r requirements.txt
```

<!-- **Contact:** Luyi Xing — lxing2@illinois.edu, Associate Professor of CS, UIUC -->
