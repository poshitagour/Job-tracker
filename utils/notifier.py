# utils/notifier.py
# Telegram notifications -- real-time alerts to your phone
# Setup: create a bot via @BotFather on Telegram, get token + chat_id
# Add to .env: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

import os
import asyncio
import aiohttp
from datetime import datetime


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

_pending_messages = []
_last_flush = datetime.now()


async def _send_raw(text: str, parse_mode: str = "HTML", disable_preview: bool = True):
    """Send a Telegram message. Silently fails if not configured."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_preview,
            }
            async with session.post(
                f"{TELEGRAM_API}/sendMessage",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"  [Telegram] Send failed: {body[:100]}")
    except Exception as e:
        print(f"  [Telegram] Error: {e}")


async def notify_applied(company: str, job_title: str, score: int, job_url: str):
    """Bot successfully applied to a job."""
    msg = (
        f"Applied!\n"
        f"Company: {company}\n"
        f"Role: {job_title}\n"
        f"AI Score: {score}/10\n"
        f"Link: {job_url}"
    )
    await _send_raw(msg)


async def notify_captcha(company: str, job_title: str, job_url: str):
    """CAPTCHA detected -- bot is paused, needs manual solve."""
    msg = (
        f"CAPTCHA -- Action Required!\n\n"
        f"Company: {company} -- {job_title}\n\n"
        f"The bot has paused. Open the browser window on your machine, "
        f"solve the CAPTCHA, then the bot will continue automatically.\n\n"
        f"Job link: {job_url}\n\n"
        f"Bot is waiting up to 3 minutes..."
    )
    await _send_raw(msg)


async def notify_high_score_job(company: str, job_title: str, score: int, job_url: str, reason: str):
    """High-scoring job found -- manual application recommended."""
    msg = (
        f"High-Score Job Found!\n\n"
        f"Company: {company}\n"
        f"Role: {job_title}\n"
        f"Score: {score}/10\n"
        f"Notes: {reason}\n\n"
        f"Recommended: Apply manually for best results\n"
        f"Link: {job_url}"
    )
    await _send_raw(msg)


async def notify_manual_apply_needed(company: str, job_title: str, job_url: str, reason: str):
    """Bot couldn't auto-apply -- flagging for manual action."""
    msg = (
        f"Manual Apply Needed\n\n"
        f"Company: {company}\n"
        f"Role: {job_title}\n"
        f"Reason: {reason}\n\n"
        f"Link: {job_url}"
    )
    await _send_raw(msg)


async def notify_session_start(platform: str, limit: int, dry_run: bool):
    """Bot started a new session."""
    mode = "DRY RUN" if dry_run else "LIVE"
    msg = (
        f"Job Bot Started\n"
        f"Platform: {platform.upper()}\n"
        f"Mode: {mode}\n"
        f"Limit: {limit} applications\n"
        f"{datetime.now().strftime('%H:%M, %d %b %Y')}"
    )
    await _send_raw(msg)


async def notify_session_end(applied: int, skipped: int, failed: int, manual_needed: int):
    """Session complete summary."""
    msg = (
        f"Session Complete\n\n"
        f"Applied: {applied}\n"
        f"Skipped (low score): {skipped}\n"
        f"Failed: {failed}\n"
        f"Manual apply needed: {manual_needed}\n\n"
        f"{datetime.now().strftime('%H:%M, %d %b %Y')}"
    )
    await _send_raw(msg)


async def notify_error(context: str, error: str):
    """Unexpected error."""
    msg = (
        f"Bot Error\n"
        f"Context: {context}\n"
        f"Error: {error[:200]}"
    )
    await _send_raw(msg)


async def notify_new_job_alert(
    title: str,
    company: str,
    location: str,
    score: int,
    cv_rec: str,
    url: str,
    posted: str,
    source: str,
    flags: list = None,
):
    """
    New job found -- formatted alert with fit score and CV recommendation.
    Only called when score >= FIT_THRESHOLD (55).
    """
    flags = flags or []
    flag_line = "\n".join(flags) + "\n" if flags else ""

    msg = (
        f"{flag_line}"
        f"NEW JOB ALERT\n"
        f"--------------------\n"
        f"Role: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Fit Score: {score}%\n"
        f"CV to Use: {cv_rec}\n"
        f"Apply: {url}\n"
        f"Posted: {posted}\n"
        f"Source: {source}\n"
        f"--------------------"
    )
    await _send_raw(msg)


async def notify_test():
    """Test notification -- run this to verify Telegram is configured."""
    msg = (
        f"Tobi's Job Bot -- Test Message\n\n"
        f"Telegram notifications are working correctly.\n"
        f"You'll receive alerts here for:\n"
        f"* Successful applications\n"
        f"* CAPTCHAs needing your solve\n"
        f"* High-score jobs to apply manually\n"
        f"* Sites where bot could not auto-apply\n"
        f"* Session summaries\n"
        f"* Irish niche job alerts (score >= 55%)"
    )
    await _send_raw(msg)
    print("Test notification sent. Check your Telegram.")
