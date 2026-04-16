#!/usr/bin/env bash
# Fast, idempotent bootstrap. Designed to not eat the routine's time budget.
# Skips pip install if playwright is already importable and skips the
# playwright CDN download if a Chromium binary is already on disk.
set -u
set -o pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

have_chromium() {
  for path in /usr/bin/chromium /usr/bin/chromium-browser \
              /usr/bin/google-chrome /usr/bin/google-chrome-stable \
              /snap/bin/chromium \
              /opt/pw-browsers/chromium-*/chrome-linux/chrome \
              /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell \
              /root/.cache/ms-playwright/chromium-*/chrome-linux/chrome \
              "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux/chrome; do
    if [ -x "$path" ]; then
      echo "Chromium available at $path"
      return 0
    fi
  done
  return 1
}

if python3 -c "import playwright" 2>/dev/null; then
  echo "playwright already installed; skipping pip install."
else
  echo "Installing python deps..."
  python3 -m pip install --no-input --disable-pip-version-check \
    -r "$DIR/requirements.txt"
fi

if have_chromium; then
  exit 0
fi

echo "No Chromium on disk; trying playwright CDN..."
if timeout 90 python3 -m playwright install chromium 2>&1; then
  echo "Playwright Chromium installed."
  exit 0
fi

echo "Playwright CDN failed; trying system packages..."
if command -v apt-get >/dev/null 2>&1; then
  for pkg in chromium chromium-browser; do
    if timeout 90 apt-get install -y --no-install-recommends "$pkg" >/dev/null 2>&1; then
      echo "Installed $pkg via apt."
      exit 0
    fi
  done
fi
if command -v dnf >/dev/null 2>&1; then
  timeout 90 dnf install -y chromium >/dev/null 2>&1 && exit 0
fi
if command -v apk >/dev/null 2>&1; then
  timeout 90 apk add --no-cache chromium >/dev/null 2>&1 && exit 0
fi

echo "WARN: no Chromium found. track_and_email.py will retry detection at runtime." >&2
exit 0
