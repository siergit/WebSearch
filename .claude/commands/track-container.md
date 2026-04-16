---
description: Scrape SeaRates container tracking and email miguel.reis@sier.pt a screenshot + data
allowed-tools: Bash(bash setup.sh), Bash(python3 track_and_email.py)
---

Run the container tracking job.

1. Ensure dependencies are installed by running: `bash setup.sh`
2. Run the scraper + mailer: `python3 track_and_email.py`
3. Report the exit status, the recipient, and any errors from stderr.

The script reads SMTP credentials from environment variables
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, optional `SMTP_PORT`, `SMTP_FROM`,
`SMTP_USE_SSL`). It defaults to the URL
<https://www.searates.com/container/tracking/?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU>
and recipient `miguel.reis@sier.pt`; both can be overridden with
`TRACKING_URL` and `TRACKING_RECIPIENT`.
