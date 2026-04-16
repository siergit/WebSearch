---
description: Scrape SeaRates container tracking and email miguel.reis@sier.pt a screenshot + data
allowed-tools: Bash(bash setup.sh), Bash(python3 track_and_email.py)
---

Run the container tracking job.

1. Run `bash setup.sh`. Don't treat Playwright CDN download failures as
   fatal — the script already falls back to system packages and to any
   pre-bundled Chromium under `/opt/pw-browsers/` or
   `~/.cache/ms-playwright/`.
2. Run `python3 track_and_email.py`. It auto-detects Chromium in:
   `/usr/bin/chromium{,-browser}`, `/usr/bin/google-chrome{,-stable}`,
   `/snap/bin/chromium`, `/opt/pw-browsers/chromium-*/chrome-linux/chrome`,
   `~/.cache/ms-playwright/chromium-*/chrome-linux/chrome`.
3. If Chromium cannot be located, try `ls /opt/pw-browsers /root/.cache/ms-playwright 2>/dev/null` to find one and re-run with
   `CHROMIUM_EXECUTABLE_PATH=<path> python3 track_and_email.py`.
4. Report: exit code of step 2, recipient, and whether email went via Resend
   or SMTP (or the stderr error chain).

The script reads SMTP credentials from environment variables
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, optional `SMTP_PORT`, `SMTP_FROM`,
`SMTP_USE_SSL`). It defaults to the URL
<https://www.searates.com/container/tracking/?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU>
and recipient `miguel.reis@sier.pt`; both can be overridden with
`TRACKING_URL` and `TRACKING_RECIPIENT`.
