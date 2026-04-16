#!/usr/bin/env bash
# Installs Python dependencies and the Playwright Chromium browser.
# Safe to re-run: pip/playwright are idempotent.
set -euo pipefail

python3 -m pip install --upgrade pip
python3 -m pip install -r "$(dirname "$0")/requirements.txt"
python3 -m playwright install --with-deps chromium
