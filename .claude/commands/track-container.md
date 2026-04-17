---
description: Scrape SeaRates container tracking and email miguel.reis@sier.pt via the Gmail connector
allowed-tools: Bash(bash setup.sh), Bash(python3 track_and_email.py), Bash(cat /tmp/container-tracking/*/run.log), Bash(ls /tmp/container-tracking/*)
---

Capture the SeaRates tracking page and email the screenshot via the Gmail
connector. The sandbox egress proxy blocks Resend and SMTP, so delivery
goes through the Gmail connector already attached to this routine.

Do exactly this, in order:

1. Run `bash setup.sh`.
2. Run `python3 track_and_email.py`. The default env sets
   `TRACKING_SKIP_EMAIL=1`, so the script only scrapes and saves
   artifacts — it will not attempt Resend/SMTP.
3. Locate the latest run log with
   `ls -1dt /tmp/container-tracking/*/run.log | head -1` and read it.
   Extract the `tracking.png` path and the `tracking.html` path (they
   are printed after `===ARTIFACTS_READY===`).
4. Use the **Gmail connector** to send an email:
   - **to:** `miguel.reis@sier.pt`
   - **subject:** `Container tracking COSU6448851830 — <UTC timestamp of the run directory, e.g. 2026-04-17 15:05 UTC>`
   - **body (plain):** Short summary: container number, source URL, timestamp, and a note that the full-page screenshot and raw HTML are attached.
   - **attachments:** `tracking.png` and `tracking.html` from the run
     directory.
5. Reply with exactly two lines:
   - `EXIT=<exit code of step 2>`
   - `EMAIL=<sent | failed: <reason>>`

If any step fails, still return those two lines plus the single-line
stderr cause.
