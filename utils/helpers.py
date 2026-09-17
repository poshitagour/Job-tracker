# utils/helpers.py
# Human-like browser behaviour — delays, typing, scrolling

import asyncio
import random
import string
from playwright.async_api import Page


async def human_delay(min_ms: int = 800, max_ms: int = 3000):
    """Random delay to mimic human behaviour."""
    delay = random.uniform(min_ms / 1000, max_ms / 1000)
    await asyncio.sleep(delay)


async def human_type(page: Page, selector: str, text: str, clear_first: bool = True):
    """Type text character by character with random delays."""
    element = page.locator(selector).first
    if clear_first:
        await element.triple_click()
        await element.press("Control+a")
        await element.press("Delete")
        await human_delay(200, 500)

    for char in text:
        await element.type(char, delay=random.randint(40, 140))
        # Occasional pause mid-word
        if random.random() < 0.05:
            await human_delay(200, 600)


async def human_click(page: Page, selector: str):
    """Click with a small random offset to avoid bot detection."""
    element = page.locator(selector).first
    await element.scroll_into_view_if_needed()
    await human_delay(300, 800)
    await element.click()
    await human_delay(400, 1000)


async def scroll_slowly(page: Page, pixels: int = 300):
    """Scroll slowly like a human reading."""
    steps = random.randint(3, 6)
    per_step = pixels // steps
    for _ in range(steps):
        await page.mouse.wheel(0, per_step)
        await human_delay(100, 300)


async def safe_fill(page: Page, selector: str, value: str, label: str = ""):
    """
    Try multiple strategies to fill a form field.
    Returns True if successful.
    """
    try:
        locator = page.locator(selector).first
        await locator.scroll_into_view_if_needed()
        await human_delay(200, 500)

        # Clear and fill
        await locator.triple_click()
        await human_delay(100, 200)
        await locator.fill(value)
        await human_delay(200, 400)
        return True
    except Exception as e:
        if label:
            print(f"  [Fill] Could not fill '{label}': {e}")
        return False


async def safe_select(page: Page, selector: str, value: str, label: str = ""):
    """Select a dropdown option by value or label."""
    try:
        locator = page.locator(selector).first
        await locator.scroll_into_view_if_needed()
        await human_delay(200, 400)
        try:
            await locator.select_option(value=value)
        except Exception:
            await locator.select_option(label=value)
        await human_delay(200, 400)
        return True
    except Exception as e:
        if label:
            print(f"  [Select] Could not select '{label}': {e}")
        return False


async def dismiss_modals(page: Page):
    """Dismiss common LinkedIn modals/popups."""
    dismiss_selectors = [
        'button[aria-label="Dismiss"]',
        'button[data-control-name="overlay.close_dropdown_trigger"]',
        '.artdeco-modal__dismiss',
        'button:has-text("Not now")',
        'button:has-text("Skip")',
        'button:has-text("Close")',
    ]
    for sel in dismiss_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await human_delay(300, 600)
        except Exception:
            pass


def clean_job_title(title: str) -> str:
    """Normalize job title for matching."""
    return title.lower().strip()


def is_excluded(text: str, excluded_keywords: list) -> bool:
    """Check if job text contains excluded keywords."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in excluded_keywords)


def truncate_text(text: str, max_chars: int = 2000) -> str:
    """Truncate text to avoid token limits."""
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    valid = string.ascii_letters + string.digits + " -_()"
    return "".join(c if c in valid else "_" for c in name)[:80]
