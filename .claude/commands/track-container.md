---
description: Scrape SeaRates container tracking and email miguel.reis@sier.pt a screenshot + data
allowed-tools: Bash(bash setup.sh), Bash(python3 track_and_email.py)
---

Run the container tracking job.

1. Run `bash setup.sh`. If it exits non-zero because the Playwright CDN is
   blocked, that is fine as long as a system Chromium is available (setup.sh
   tries `apt-get install chromium`). Check `/usr/bin/chromium` or
   `/usr/bin/chromium-browser`; if present, continue.
2. Run `python3 track_and_email.py`. The script auto-detects the system
   Chromium binary, so no extra flags are needed.
3. If Chromium is still missing, install it with
   `sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser`
   and retry step 2. As a last resort, set `CHROMIUM_EXECUTABLE_PATH` to any
   chrome/chromium binary on the system.
4. Report the exit status of step 2, the recipient, and any errors from
   stderr.

The script reads SMTP credentials from environment variables
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, optional `SMTP_PORT`, `SMTP_FROM`,
`SMTP_USE_SSL`). It defaults to the URL
<https://www.searates.com/container/tracking/?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU>
and recipient `miguel.reis@sier.pt`; both can be overridden with
`TRACKING_URL` and `TRACKING_RECIPIENT`.
