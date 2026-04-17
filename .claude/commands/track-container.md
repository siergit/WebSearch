---
description: Scrape SeaRates container tracking and email miguel.reis@sier.pt (via Resend)
allowed-tools: Bash(bash setup.sh), Bash(python3 track_and_email.py), Bash(cat /tmp/container-tracking/*/run.log)
---

Run the container tracking job. Do this literally and do not paraphrase.

1. `bash setup.sh`
2. `python3 track_and_email.py` — note the exit code.
3. `cat $(ls -1dt /tmp/container-tracking/*/run.log | head -1)`
4. Reply with ONE fenced code block containing the full `run.log` contents,
   exactly as produced. No summarizing, no translating, no rewriting.
5. After the code block add one final line: `EXIT=<code>`.

Nothing else. No commentary, no conclusions.
