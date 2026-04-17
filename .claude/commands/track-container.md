---
description: Scrape SeaRates container tracking and email miguel.reis@sier.pt a screenshot + data
allowed-tools: Bash(bash setup.sh), Bash(python3 track_and_email.py), Bash(cat /tmp/container-tracking/*/run.log), Bash(ls /tmp/container-tracking/)
---

Run the container tracking job. **Follow this exactly and do not paraphrase.**

1. `bash setup.sh`
2. `python3 track_and_email.py`   — note the exit code.
3. Find the log file. The script prints `===RUN_LOG_PATH=== <path>` at the
   start; if you missed it, use
   `ls -1dt /tmp/container-tracking/*/run.log | head -1`.
4. **Cat that log file verbatim and paste its full contents back.** Do
   NOT summarize, rewrite, or translate the log. Paste it inside a fenced
   code block exactly as produced.
5. After the log, add one final line: `EXIT=<code>`.

That is the entire output. No other commentary.