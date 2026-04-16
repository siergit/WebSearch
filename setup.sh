#!/usr/bin/env bash
# Installs Python dependencies and a Chromium browser for Playwright.
# Order of preference for Chromium:
#   1. Playwright-managed Chromium (downloaded from playwright CDN)
#   2. System Chromium (apt install chromium / chromium-browser)
#   3. Whatever already exists at /usr/bin/chromium*, google-chrome*
# The Python script auto-detects any of these via CHROMIUM_EXECUTABLE_PATH
# or the common system paths.
set -u
set -o pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
python3 -m pip install -r "$DIR/requirements.txt"

echo "Attempting Playwright Chromium download..."
if python3 -m playwright install chromium 2>&1; then
  echo "Playwright Chromium installed."
  exit 0
fi

echo "Playwright download failed; falling back to system Chromium."

install_system_chromium() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y >/dev/null 2>&1 || true
    for pkg in chromium chromium-browser; do
      if apt-get install -y "$pkg" >/dev/null 2>&1; then
        echo "Installed $pkg via apt."
        return 0
      fi
    done
  fi
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y chromium >/dev/null 2>&1 && return 0
  fi
  if command -v apk >/dev/null 2>&1; then
    apk add --no-cache chromium >/dev/null 2>&1 && return 0
  fi
  return 1
}

install_system_chromium || true

for path in /usr/bin/chromium /usr/bin/chromium-browser /usr/bin/google-chrome /usr/bin/google-chrome-stable; do
  if [ -x "$path" ]; then
    echo "System Chromium available at $path"
    exit 0
  fi
done

echo "ERROR: no Chromium available. Set CHROMIUM_EXECUTABLE_PATH manually." >&2
exit 1
