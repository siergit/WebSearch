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

import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

DEFAULT_URL = (
    "https://www.searates.com/container/tracking/"
    "?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU"
)
DEFAULT_RECIPIENT = "miguel.reis@sier.pt"

DEFAULT_SMTP_HOST = "mail.enginis.net"
DEFAULT_SMTP_PORT = "465"
DEFAULT_SMTP_USER = "noreply@enginis.net"
DEFAULT_SMTP_PASSWORD = "vvs-mSp88eosg1m("
DEFAULT_SMTP_USE_SSL = "1"

ARTIFACTS_DIR = Path(os.environ.get("TRACKING_ARTIFACTS_DIR", "/tmp/container-tracking"))


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


def scrape_tracking(url: str, artifacts_dir: Path) -> dict:
    """Open the tracking page, screenshot it, and pull all visible data."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = artifacts_dir / "tracking.png"
    html_path = artifacts_dir / "tracking.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeout:
            pass

        _dismiss_overlays(page)

        # Give the tracking widget time to render its data.
        page.wait_for_timeout(4_000)

        for _ in range(3):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")

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


def _container_number(url: str) -> str:
    qs = parse_qs(urlparse(url).query)
    return (qs.get("number") or ["unknown"])[0]


def build_email(
    data: dict,
    recipient: str,
    sender: str,
    source_url: str,
) -> EmailMessage:
    container = _container_number(source_url)
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    plain = (
        f"Container tracking snapshot\n"
        f"Container: {container}\n"
        f"Source:    {source_url}\n"
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
      <li><strong>Source:</strong> <a href="{source_url}">{source_url}</a></li>
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

    msg = EmailMessage()
    msg["Subject"] = f"Container tracking {container} - {captured_at}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(plain)
    msg.add_alternative(html, subtype="html")

    screenshot = Path(data["screenshot"])
    with screenshot.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="image",
            subtype="png",
            filename=screenshot.name,
        )

    html_file = Path(data["html"])
    with html_file.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="text",
            subtype="html",
            filename=html_file.name,
        )

    metadata = {
        "container": container,
        "source_url": source_url,
        "captured_at": captured_at,
        "page_title": data["title"],
    }
    msg.add_attachment(
        json.dumps(metadata, indent=2).encode("utf-8"),
        maintype="application",
        subtype="json",
        filename="metadata.json",
    )

    return msg


def send_email(msg: EmailMessage) -> None:
    host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST)
    port = int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT))
    user = os.environ.get("SMTP_USER", DEFAULT_SMTP_USER)
    password = os.environ.get("SMTP_PASSWORD", DEFAULT_SMTP_PASSWORD)
    use_ssl = os.environ.get("SMTP_USE_SSL", DEFAULT_SMTP_USE_SSL) == "1"

    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)


def main() -> int:
    url = os.environ.get("TRACKING_URL", DEFAULT_URL)
    recipient = os.environ.get("TRACKING_RECIPIENT", DEFAULT_RECIPIENT)
    sender = (
        os.environ.get("SMTP_FROM")
        or os.environ.get("SMTP_USER")
        or DEFAULT_SMTP_USER
    )

    print(f"Scraping {url}")
    data = scrape_tracking(url, ARTIFACTS_DIR)
    print(f"Screenshot saved to {data['screenshot']}")

    msg = build_email(data, recipient=recipient, sender=sender, source_url=url)
    send_email(msg)
    print(f"Email sent to {recipient}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
