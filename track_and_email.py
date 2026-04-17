#!/usr/bin/env python3
"""Scrape SeaRates container tracking and email the result.

Designed to be invoked from a Claude Code routine (remote mode). Defaults are
wired to the Enginis SMTP relay; every value can be overridden via env vars.

Env vars (all optional, overriding the defaults below):
    SMTP_HOST          SMTP server hostname
    SMTP_PORT          SMTP port
    SMTP_USER          SMTP username
    SMTP_PASSWORD      SMTP password
    SMTP_FROM          envelope sender (defaults to SMTP_USER)
    SMTP_USE_SSL       "1" for SMTPS (port 465), "0" for STARTTLS
    TRACKING_URL       override the SeaRates URL
    TRACKING_RECIPIENT override the recipient
"""

from __future__ import annotations

import base64
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

SYSTEM_CHROMIUM_CANDIDATES = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
)

# Search patterns for Playwright browsers that may already be pre-installed in
# the sandbox (this is how Claude's remote routines ship Chromium).
PW_BROWSER_GLOBS = (
    "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
    "/root/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
    "/root/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux/headless_shell",
    str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux/chrome"),
)


def _resolve_chromium_path() -> str | None:
    """Return a usable Chromium executable, or None to let Playwright decide."""
    import glob

    explicit = os.environ.get("CHROMIUM_EXECUTABLE_PATH")
    if explicit:
        return explicit if Path(explicit).exists() else None

    for candidate in SYSTEM_CHROMIUM_CANDIDATES:
        if Path(candidate).exists():
            return candidate

    # Highest version wins (lexicographic sort is fine for chromium-<int>).
    best: str | None = None
    for pattern in PW_BROWSER_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            best = matches[-1]
            break
    return best

DEFAULT_URL = (
    "https://www.searates.com/container/tracking/"
    "?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU"
)
# COSCO is the carrier for COSU-prefixed containers. The container
# endpoint returns the real tracker UI for a container number; the bill
# endpoint is for Bill of Lading IDs (different ID format).
DEFAULT_COSCO_URL_TEMPLATE = (
    "https://elines.coscoshipping.com/ebtracking/public/container/{number}"
)
DEFAULT_RECIPIENT = "miguel.reis@sier.pt"

DEFAULT_SMTP_HOST = "mail.enginis.net"
DEFAULT_SMTP_PORT = "465"
DEFAULT_SMTP_USER = "noreply@enginis.net"
DEFAULT_SMTP_PASSWORD = "vvs-mSp88eosg1m("
DEFAULT_SMTP_USE_SSL = "1"

# Resend is used first because sandbox environments for the remote routine
# typically allow outbound HTTPS but block SMTP ports.
RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_RESEND_API_KEY = "re_dmJ8MoeU_BpE9sC8Xn8CJMCJ5BQzaGn1t"
DEFAULT_RESEND_FROM = "Container Tracking <noreply@resend.unikrobotics.com>"

ARTIFACTS_BASE_DIR = Path(os.environ.get("TRACKING_ARTIFACTS_DIR", "/tmp/container-tracking"))
RUN_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
ARTIFACTS_DIR = ARTIFACTS_BASE_DIR / RUN_TIMESTAMP


def _dismiss_overlays(page) -> None:
    """Best-effort dismissal of cookie / consent / popup overlays."""
    selectors = [
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "button:has-text('Agree')",
        "button:has-text('I agree')",
        "button:has-text('Got it')",
        "#onetrust-accept-btn-handler",
        "[aria-label='Close']",
        "button[aria-label='close']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1000):
                locator.click(timeout=1500)
                page.wait_for_timeout(500)
        except Exception:
            continue


_ACTIVE_TAGS = ("script", "iframe", "noscript", "object", "embed", "applet")


def _sanitize_html(html: str) -> str:
    """Strip scripts/iframes/event handlers so the saved HTML is safe to
    attach to an email. Antivirus products (e.g. ESET) flag the raw
    SeaRates HTML because of obfuscated/minified JS in <script> blocks —
    heuristic catch as JS/Kryptik. The sanitized copy keeps markup and
    styling but removes executable content."""
    for tag in _ACTIVE_TAGS:
        html = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}\s*>",
            "",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(rf"<{tag}\b[^>]*/?>", "", html, flags=re.IGNORECASE)
    html = re.sub(
        r"\s+on\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)",
        "",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(
        r"(href|src|action)\s*=\s*(\"\s*javascript:[^\"]*\"|'\s*javascript:[^']*'|javascript:[^\s>]+)",
        r'\1="#"',
        html,
        flags=re.IGNORECASE,
    )
    return html


# Tracking-specific vocabulary. Avoid weak terms that also appear in
# marketing copy ("bill of lading", "freight tracking") — those trigger
# false positives on the SeaRates landing page FAQ. We restrict to
# abbreviations and labels that only appear next to real data.
_TRACKING_DATA_TERMS = re.compile(
    r"\bPOL\b|\bPOD\b|\bETA\b|\bETD\b|"
    r"port of (loading|discharge)|place of (receipt|delivery)|"
    r"vessel\s*(name|voyage)?\b|voyage\s*(no|number)|"
    r"container\s*(no|number)|bill\s*of\s*lading\s*(no|number)|"
    r"estimated (arrival|departure)|actual (arrival|departure)|"
    r"last location|empty (pickup|return)|gate\s?(in|out)",
    re.IGNORECASE,
)

_DATE_PATTERN = re.compile(
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|"
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|"
    r"\b\d{1,2}\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4}\b",
    re.IGNORECASE,
)


def _has_tracking_data(text: str, container: str = "") -> bool:
    """Accept a capture only if it has the container number AND at least
    one date-like token AND at least one tracking-specific keyword. This
    discriminates between a rendered tracker widget and a marketing page
    whose FAQ happens to mention tracking vocabulary."""
    if not text:
        return False
    lowered = text.lower()
    if "dns cache overflow" in lowered:
        return False
    # COSCO returns {"message":"无数据"} ("no data") for unknown IDs.
    if "无数据" in text or '"message":"no data"' in lowered:
        return False
    if container and container.upper() not in text.upper():
        return False
    if not _DATE_PATTERN.search(text):
        return False
    return bool(_TRACKING_DATA_TERMS.search(text))


def _wait_for_tracking_data(
    page, label: str, container: str, timeout_ms: int = 45_000
) -> bool:
    """Wait until the tracker widget renders real data: the container
    number appears in the body AND at least one date."""
    container_js = json.dumps(container)
    try:
        page.wait_for_function(
            "(needle) => {"
            "  const t = (document.body && document.body.innerText) || '';"
            "  if (!needle || !t.toUpperCase().includes(needle.toUpperCase())) return false;"
            "  const date = /\\b\\d{4}[-/]\\d{1,2}[-/]\\d{1,2}\\b|"
            "\\b\\d{1,2}[-/]\\d{1,2}[-/]\\d{2,4}\\b|"
            "\\b\\d{1,2}\\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
            "\\s+\\d{2,4}\\b/i;"
            "  return date.test(t);"
            "}",
            arg=container,
            timeout=timeout_ms,
        )
        print(f"  {label}: tracker populated with {container} + date", flush=True)
        return True
    except PlaywrightTimeout:
        print(
            f"  {label}: tracker did not populate within "
            f"{timeout_ms/1000:.0f}s (container={container})",
            flush=True,
        )
        return False


def _scrape_once(url: str, artifacts_dir: Path, container: str = "") -> dict:
    screenshot_path = artifacts_dir / "tracking.png"
    html_path = artifacts_dir / "tracking.html"
    raw_html_path = artifacts_dir / "tracking-raw.html"

    launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--ignore-certificate-errors"]}
    chromium_path = _resolve_chromium_path()
    if chromium_path:
        launch_kwargs["executable_path"] = chromium_path
        print(f"Using Chromium: {chromium_path}", flush=True)
    else:
        print("Using Playwright-managed Chromium", flush=True)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as exc:
            if "executable_path" in launch_kwargs:
                raise
            raise RuntimeError(
                "No Chromium available. Run setup.sh or set "
                "CHROMIUM_EXECUTABLE_PATH to a chromium/chrome binary. "
                f"Original error: {exc}"
            ) from exc
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()
        print(f"Loading page (timeout 45s)...", flush=True)
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)

        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeout:
            pass

        _dismiss_overlays(page)
        print("Rendering tracking widget...", flush=True)
        populated = _wait_for_tracking_data(
            page, "widget", container=container, timeout_ms=45_000
        )

        for _ in range(3):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(600)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        # If the widget populated, try to scroll it into view so the
        # full-page screenshot is anchored to the data rather than the
        # hero banner.
        if populated and container:
            try:
                target = page.get_by_text(container, exact=False).first
                target.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
            except Exception:
                pass

        page.screenshot(path=str(screenshot_path), full_page=True)
        raw_html = page.content()
        raw_html_path.write_text(raw_html, encoding="utf-8")
        sanitized = _sanitize_html(raw_html)
        html_path.write_text(sanitized, encoding="utf-8")
        print(
            f"HTML sanitized: raw={len(raw_html)} bytes, "
            f"sanitized={len(sanitized)} bytes",
            flush=True,
        )

        body_text = page.inner_text("body")
        title = page.title()
        final_url = page.url

        browser.close()

    return {
        "title": title,
        "url": final_url,
        "text": body_text,
        "screenshot": screenshot_path,
        "html": html_path,
    }


def scrape_tracking(url: str, artifacts_dir: Path) -> dict:
    """Scrape a tracking source, preferring COSCO's official tracker and
    falling back to SeaRates.

    Retries each source if the captured page is either the proxy's DNS
    error page or a marketing landing page that never rendered the real
    tracking widget."""
    import time

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    container = _container_number(url)

    sources: list[tuple[str, str]] = []
    if os.environ.get("TRACKING_SKIP_COSCO") != "1":
        cosco_url = os.environ.get(
            "COSCO_URL", DEFAULT_COSCO_URL_TEMPLATE.format(number=container)
        )
        sources.append(("cosco", cosco_url))
    sources.append(("searates", url))

    last: dict | None = None
    for source, src_url in sources:
        for attempt in range(1, 3):
            print(f"Scrape source={source} attempt {attempt}/2 url={src_url}", flush=True)
            try:
                last = _scrape_once(src_url, artifacts_dir, container=container)
                last["source"] = source
                last["source_url"] = src_url
            except Exception as exc:
                print(f"  {source} attempt {attempt} raised: {exc}", flush=True)
                time.sleep(5 * attempt)
                continue

            if not _html_looks_real(last["text"]):
                preview = last["text"][:120].replace("\n", " ")
                print(
                    f"  {source} attempt {attempt}: proxy error page "
                    f"({preview!r}); retrying after backoff.",
                    flush=True,
                )
                time.sleep(5 * attempt)
                continue

            if _has_tracking_data(last["text"], container=container):
                print(f"  {source}: has tracking data — using this source", flush=True)
                return last

            preview = last["text"][:200].replace("\n", " ")
            print(
                f"  {source} attempt {attempt}: page has no tracking data. "
                f"Preview: {preview!r}",
                flush=True,
            )
            time.sleep(3)

        print(f"  {source} exhausted; trying next source", flush=True)

    assert last is not None
    last.setdefault("source", "unknown")
    last.setdefault("source_url", url)
    return last


def _container_number(url: str) -> str:
    qs = parse_qs(urlparse(url).query)
    return (qs.get("number") or ["unknown"])[0]


_SOURCE_LABELS = {
    "cosco": "COSCO eLines (official)",
    "searates": "SeaRates (aggregator)",
    "unknown": "unknown",
}


def _email_parts(data: dict, source_url: str) -> dict:
    """Shared subject/text/html/attachments used by both SMTP and Resend paths."""
    container = _container_number(source_url)
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    source_key = data.get("source", "unknown")
    source_label = _SOURCE_LABELS.get(source_key, source_key)
    actual_source_url = data.get("source_url") or source_url

    plain = (
        f"Container tracking snapshot\n"
        f"Container: {container}\n"
        f"Source:    {source_label}\n"
        f"URL:       {actual_source_url}\n"
        f"Captured:  {captured_at}\n"
        f"Page title: {data['title']}\n"
        f"\n"
        f"--- Page text ---\n"
        f"{data['text']}\n"
    )

    html = f"""\
<html>
  <body style="font-family: Arial, sans-serif;">
    <h2>Container tracking snapshot</h2>
    <ul>
      <li><strong>Container:</strong> {container}</li>
      <li><strong>Source:</strong> {source_label}</li>
      <li><strong>URL:</strong> <a href="{actual_source_url}">{actual_source_url}</a></li>
      <li><strong>Captured:</strong> {captured_at}</li>
      <li><strong>Page title:</strong> {data['title']}</li>
    </ul>
    <p>The full-page screenshot is attached along with a saved HTML copy.
       Raw scraped text is included below.</p>
    <pre style="white-space: pre-wrap; background:#f6f8fa; padding:12px; border-radius:6px;">
{data['text']}
    </pre>
  </body>
</html>
"""

    metadata = {
        "container": container,
        "source": source_key,
        "source_label": source_label,
        "source_url": actual_source_url,
        "captured_at": captured_at,
        "page_title": data["title"],
    }

    attachments: list[dict] = []
    for path in (Path(data["screenshot"]), Path(data["html"])):
        attachments.append({
            "filename": path.name,
            "bytes": path.read_bytes(),
        })
    attachments.append({
        "filename": "metadata.json",
        "bytes": json.dumps(metadata, indent=2).encode("utf-8"),
    })

    return {
        "subject": f"Container tracking {container} via {source_label} - {captured_at}",
        "text": plain,
        "html": html,
        "attachments": attachments,
    }


def build_email(
    data: dict,
    recipient: str,
    sender: str,
    source_url: str,
) -> EmailMessage:
    parts = _email_parts(data, source_url)
    msg = EmailMessage()
    msg["Subject"] = parts["subject"]
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(parts["text"])
    msg.add_alternative(parts["html"], subtype="html")
    for att in parts["attachments"]:
        filename = att["filename"]
        if filename.endswith(".png"):
            maintype, subtype = "image", "png"
        elif filename.endswith(".html"):
            maintype, subtype = "text", "html"
        elif filename.endswith(".json"):
            maintype, subtype = "application", "json"
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(att["bytes"], maintype=maintype, subtype=subtype, filename=filename)
    return msg


def send_via_resend(data: dict, recipient: str, source_url: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY", DEFAULT_RESEND_API_KEY)
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not set")
    sender = os.environ.get("RESEND_FROM", DEFAULT_RESEND_FROM)
    print(
        f"Resend sender={sender!r}  to={recipient!r}  "
        f"api_key_prefix={api_key[:10]}...",
        file=sys.stderr,
        flush=True,
    )

    parts = _email_parts(data, source_url)
    payload = {
        "from": sender,
        "to": [recipient],
        "subject": parts["subject"],
        "text": parts["text"],
        "html": parts["html"],
        "attachments": [
            {
                "filename": att["filename"],
                "content": base64.b64encode(att["bytes"]).decode("ascii"),
            }
            for att in parts["attachments"]
        ],
    }

    body_bytes = json.dumps(payload).encode("utf-8")
    print(f"Resend payload size: {len(body_bytes)} bytes", file=sys.stderr, flush=True)

    import time

    browser_ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    def _warm_up() -> bool:
        """Cheap HEAD to prime the sandbox proxy's DNS cache for
        api.resend.com. Returns True if we got any non-5xx response."""
        req = urllib.request.Request(
            RESEND_API_URL,
            method="HEAD",
            headers={"User-Agent": browser_ua},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"  Resend warm-up HEAD: {resp.status}", file=sys.stderr, flush=True)
                return True
        except urllib.error.HTTPError as exc:
            body = exc.read(200).decode("utf-8", errors="replace")
            print(f"  Resend warm-up HEAD: HTTP {exc.code} {body!r}",
                  file=sys.stderr, flush=True)
            return exc.code < 500
        except Exception as exc:
            print(f"  Resend warm-up HEAD failed: {exc}", file=sys.stderr, flush=True)
            return False

    # The sandbox proxy returns HTTP 503 "DNS cache overflow" intermittently
    # for every host (including the Playwright browser's own traffic). We
    # retry with a longer backoff than usual so the cache has time to free
    # entries, and do a cheap HEAD first to prime it.
    backoffs = (10, 30, 60)  # seconds between attempts 1->2, 2->3, 3->4
    last_exc: Exception | None = None
    for attempt in range(1, 5):
        if attempt > 1:
            wait = backoffs[min(attempt - 2, len(backoffs) - 1)]
            print(f"  waiting {wait}s before Resend retry {attempt}",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
            _warm_up()

        req = urllib.request.Request(
            RESEND_API_URL,
            data=body_bytes,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Cloudflare in front of api.resend.com rejects the default
                # "Python-urllib/X" UA with error 1010. Use a browser-like UA.
                "User-Agent": browser_ua,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                print(
                    f"===RESEND_RESPONSE_BEGIN===\nHTTP {resp.status}\n{body}\n"
                    f"===RESEND_RESPONSE_END===",
                    file=sys.stderr,
                    flush=True,
                )
                return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(
                f"===RESEND_RESPONSE_BEGIN===\nHTTP {exc.code} (attempt {attempt}/4)\n"
                f"{detail}\n===RESEND_RESPONSE_END===",
                file=sys.stderr,
                flush=True,
            )
            last_exc = RuntimeError(f"Resend HTTP {exc.code}: {detail}")
            if exc.code in (502, 503, 504, 520, 521, 522, 523, 524):
                continue
            raise last_exc from exc
        except Exception as exc:
            print(
                f"===RESEND_RESPONSE_BEGIN===\n{exc.__class__.__name__} "
                f"(attempt {attempt}/4): {exc}\n===RESEND_RESPONSE_END===",
                file=sys.stderr,
                flush=True,
            )
            last_exc = exc
            continue

    raise last_exc or RuntimeError("Resend failed for unknown reason")


def _smtp_attempts() -> list[tuple[int, bool]]:
    """Ports + mode (use_ssl) to try, in order. First the configured one, then
    fall back to the other standard submission ports so we survive sandboxes
    that block one port but not another."""
    env_port = int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT))
    env_ssl = os.environ.get("SMTP_USE_SSL", DEFAULT_SMTP_USE_SSL) == "1"
    preferred = (env_port, env_ssl)
    fallbacks = [(465, True), (587, False), (2525, False), (25, False)]
    seen = {preferred}
    ordered = [preferred]
    for attempt in fallbacks:
        if attempt not in seen:
            ordered.append(attempt)
            seen.add(attempt)
    return ordered


def _send_via_smtp(msg: EmailMessage, host: str, port: int, use_ssl: bool,
                   user: str, password: str, timeout: int = 20) -> None:
    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
            smtp.login(user, password)
            smtp.send_message(msg)


def send_email(msg: EmailMessage) -> None:
    host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST)
    user = os.environ.get("SMTP_USER", DEFAULT_SMTP_USER)
    password = os.environ.get("SMTP_PASSWORD", DEFAULT_SMTP_PASSWORD)

    errors: list[str] = []
    for port, use_ssl in _smtp_attempts():
        mode = "SSL" if use_ssl else "STARTTLS"
        try:
            print(f"SMTP attempt {host}:{port} ({mode})", file=sys.stderr)
            _send_via_smtp(msg, host, port, use_ssl, user, password)
            print(f"SMTP success via {host}:{port} ({mode})", file=sys.stderr)
            return
        except Exception as exc:
            errors.append(f"{host}:{port} {mode} -> {exc.__class__.__name__}: {exc}")
            continue

    raise RuntimeError(
        "All SMTP attempts failed. The routine sandbox likely blocks outbound "
        "SMTP. Provide an HTTP email relay (e.g. Resend/Mailgun API) or "
        "configure SMTP_HOST/SMTP_PORT to a reachable relay. Details:\n  "
        + "\n  ".join(errors)
    )


def _probe_connectivity(hosts: tuple[str, ...]) -> None:
    """HEAD request each host and log the outcome. Doesn't fail the run —
    just writes the verdict so the routine log shows whether egress is open."""
    print("===CONNECTIVITY_PROBE===", flush=True)
    ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    for host in hosts:
        url = f"https://{host}/"
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                print(f"  {host}: OK ({resp.status})", flush=True)
        except urllib.error.HTTPError as exc:
            body = exc.read(200).decode("utf-8", errors="replace")
            print(f"  {host}: HTTP {exc.code} {body!r}", flush=True)
        except Exception as exc:
            print(f"  {host}: {exc.__class__.__name__}: {exc}", flush=True)
    print("===CONNECTIVITY_PROBE_END===", flush=True)


def _html_looks_real(html: str) -> bool:
    """Heuristic: true if the captured page looks like a real site
    response rather than a proxy/edge error page produced by the routine
    sandbox. Doesn't require carrier-specific keywords — source
    selection is handled by _has_tracking_data upstream."""
    if not html:
        return False
    lowered = html.lower()
    if "host not in allowlist" in lowered:
        return False
    if "dns cache overflow" in lowered:
        return False
    # Real pages render meaningful content; the proxy error pages are
    # tiny single-line strings.
    return len(html.strip()) > 200


class _Tee:
    """Duplicate writes to the original stream and a log file."""
    def __init__(self, original, log_file):
        self._original = original
        self._log = log_file
    def write(self, text):
        self._original.write(text)
        self._log.write(text)
        self._original.flush()
        self._log.flush()
    def flush(self):
        self._original.flush()
        self._log.flush()
    def __getattr__(self, name):
        return getattr(self._original, name)


def main() -> int:
    url = os.environ.get("TRACKING_URL", DEFAULT_URL)
    recipient = os.environ.get("TRACKING_RECIPIENT", DEFAULT_RECIPIENT)
    sender = (
        os.environ.get("SMTP_FROM")
        or os.environ.get("SMTP_USER")
        or DEFAULT_SMTP_USER
    )

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = ARTIFACTS_DIR / "run.log"
    log_file = log_path.open("w", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)

    print(f"===RUN_LOG_PATH=== {log_path}", flush=True)

    # Connectivity probes so we know at-a-glance whether the sandbox
    # egress allowlist lets us talk to the hosts we need. Keep the list
    # minimal — the sandbox proxy has a small DNS cache and extra hosts
    # evict the ones we actually need. Override with
    # TRACKING_PROBE_HOSTS="host1,host2,...".
    default_hosts = ("api.resend.com", "www.searates.com")
    env_hosts = os.environ.get("TRACKING_PROBE_HOSTS", "").strip()
    hosts = tuple(h.strip() for h in env_hosts.split(",") if h.strip()) or default_hosts
    _probe_connectivity(hosts)

    print(f"Scraping {url}", flush=True)
    data = scrape_tracking(url, ARTIFACTS_DIR)
    print(f"Screenshot saved to {data['screenshot']}", flush=True)
    print(f"HTML saved to {data['html']}", flush=True)
    print(f"Winning source: {data.get('source', 'unknown')} ({data.get('source_url')})", flush=True)

    if not _html_looks_real(data["text"]):
        preview = data["text"][:400].replace("\n", " ")
        print(
            f"===SCRAPE_WARNING=== Captured page looks like a proxy/error "
            f"page. Preview: {preview!r}",
            file=sys.stderr,
            flush=True,
        )
    elif not _has_tracking_data(data["text"], container=_container_number(url)):
        preview = data["text"][:400].replace("\n", " ")
        print(
            f"===SCRAPE_WARNING=== Page loaded but no tracking data "
            f"detected (checked COSCO + SeaRates). Preview: {preview!r}",
            file=sys.stderr,
            flush=True,
        )

    skip_email = os.environ.get("TRACKING_SKIP_EMAIL") == "1"
    if skip_email:
        print(
            "TRACKING_SKIP_EMAIL=1 set — skipping Python-side email. "
            "Caller is expected to deliver via Gmail connector or similar.",
            flush=True,
        )
        print(f"===ARTIFACTS_READY=== {ARTIFACTS_DIR}", flush=True)
        print(f"  screenshot: {data['screenshot']}", flush=True)
        print(f"  html:       {data['html']}", flush=True)
        print(f"  recipient:  {recipient}", flush=True)
        return 0

    errors: list[str] = []

    if os.environ.get("RESEND_API_KEY", DEFAULT_RESEND_API_KEY):
        try:
            print("Sending via Resend HTTPS", file=sys.stderr, flush=True)
            send_via_resend(data, recipient=recipient, source_url=url)
            print(f"Email sent to {recipient} via Resend", flush=True)
            return 0
        except Exception as exc:
            errors.append(f"Resend: {exc}")
            print(f"Resend send failed: {exc}", file=sys.stderr, flush=True)

    # SMTP ports are blocked in the Claude Code routine sandbox, so SMTP
    # is opt-in via TRACKING_TRY_SMTP=1. Default is to skip it so we don't
    # burn ~80 seconds in timeouts per run.
    if os.environ.get("TRACKING_TRY_SMTP") == "1":
        try:
            print("Falling back to SMTP", file=sys.stderr, flush=True)
            msg = build_email(data, recipient=recipient, sender=sender, source_url=url)
            send_email(msg)
            print(f"Email sent to {recipient} via SMTP", flush=True)
            return 0
        except Exception as exc:
            errors.append(f"SMTP: {exc}")
            print(f"SMTP send failed: {exc}", file=sys.stderr, flush=True)
    else:
        print(
            "SMTP path skipped (set TRACKING_TRY_SMTP=1 to attempt it; "
            "ports are blocked by the routine sandbox).",
            file=sys.stderr,
            flush=True,
        )

    print(
        "All email paths failed.\n"
        + "\n".join(errors)
        + f"\nArtifacts retained at:\n  {data['screenshot']}\n  {data['html']}",
        file=sys.stderr,
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
