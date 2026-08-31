#!/usr/bin/env bash
#
# UMCCI Checker — end-to-end run.
#
# Drives stages 2 (preprocess) and 3 (security analysis) in a single invocation, because
# the virtual Matter device built in stage 2 must stay running for stage 3 to attach to
# it. Console output is written to stage 4.
#
# Usage: ./pipeline_harness/umcci-checker/run.sh [args passed to umcci_checker.py]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ANALYSIS_DIR="$REPO_ROOT/3_security_analysis/umcci-checker"
OUTPUT_DIR="$REPO_ROOT/4_analysis_output/umcci-checker"

mkdir -p "$OUTPUT_DIR"

echo "==> Installing Python dependencies"
python3 -m pip install --quiet -r "$ANALYSIS_DIR/requirements.txt"

echo "==> Running UMCCI Checker (stages 2 and 3)"
cd "$ANALYSIS_DIR"
python3 umcci_checker.py "$@" 2>&1 | tee "$OUTPUT_DIR/last_run.log"

echo "==> Report written to 4_analysis_output/umcci-checker/last_run.log"
