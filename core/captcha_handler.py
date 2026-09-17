# core/captcha_handler.py
# Detects CAPTCHAs, pauses the bot, notifies Tobi, waits for manual solve

import asyncio
from playwright.async_api import Page
from utils.notifier import notify_captcha
from utils.helpers import human_delay


# CAPTCHA detection signatures
CAPTCHA_SELECTORS = [
    # reCAPTCHA
    'iframe[src*="recaptcha"]',
    'iframe[src*="google.com/recaptcha"]',
    '.g-recaptcha',
    '#recaptcha',
    '[data-sitekey]',
    # hCaptcha
    'iframe[src*="hcaptcha"]',
    '.h-captcha',
    # Cloudflare
    'iframe[src*="cloudflare"]',
    '#challenge-form',
    '.cf-browser-verification',
    # Generic
    'iframe[title*="captcha" i]',
    'iframe[title*="challenge" i]',
    '[class*="captcha"]',
    '[id*="captcha"]',
]

CAPTCHA_TEXT_SIGNALS = [
    "verify you are human",
    "prove you're not a robot",
    "security check",
    "captcha",
    "i'm not a robot",
    "bot detection",
    "verify you're human",
    "access denied",
    "please verify",
    "challenge",
]

MAX_WAIT_SECONDS = 180  # Wait up to 3 minutes for manual solve


async def detect_captcha(page: Page) -> bool:
    """Returns True if a CAPTCHA is detected on the current page."""
    # Check for CAPTCHA elements
    for selector in CAPTCHA_SELECTORS:
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=500):
                return True
        except Exception:
            pass

    # Check page text for CAPTCHA signals
    try:
        page_text = (await page.content()).lower()
        if any(signal in page_text for signal in CAPTCHA_TEXT_SIGNALS):
            # Double-check it's actually visible, not just in source
            body_text = await page.evaluate("document.body.innerText.toLowerCase()")
            if any(signal in body_text for signal in CAPTCHA_TEXT_SIGNALS[:4]):
                return True
    except Exception:
        pass

    return False


async def handle_captcha(page: Page, company: str, job_title: str, job_url: str) -> bool:
    """
    CAPTCHA detected. Notifies Tobi, waits for manual solve.
    Returns True if solved (page moved past CAPTCHA), False if timed out.
    """
    print(f"\n  🚨 CAPTCHA DETECTED — {company} | {job_title}")
    print(f"  ⏸  Bot paused. Please solve the CAPTCHA in the browser window.")
    print(f"  ⏳ Waiting up to {MAX_WAIT_SECONDS} seconds...")

    # Send Telegram alert
    await notify_captcha(company, job_title, job_url)

    # Poll every 5 seconds to check if CAPTCHA is gone
    elapsed = 0
    poll_interval = 5

    while elapsed < MAX_WAIT_SECONDS:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        captcha_still_present = await detect_captcha(page)
        if not captcha_still_present:
            print(f"  ✓ CAPTCHA solved! Resuming after {elapsed}s...")
            await human_delay(1000, 2000)
            return True

        remaining = MAX_WAIT_SECONDS - elapsed
        if elapsed % 30 == 0:  # Print reminder every 30s
            print(f"  ⏳ Still waiting for CAPTCHA solve... ({remaining}s remaining)")

    print(f"  ✗ CAPTCHA timed out after {MAX_WAIT_SECONDS}s. Skipping this application.")
    return False


async def check_and_handle_captcha(page: Page, company: str, job_title: str, job_url: str) -> bool:
    """
    Convenience function — checks for CAPTCHA and handles if found.
    Returns True if we can proceed (no CAPTCHA or solved), False if stuck.
    """
    if await detect_captcha(page):
        return await handle_captcha(page, company, job_title, job_url)
    return True
