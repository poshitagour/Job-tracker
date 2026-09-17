# core/universal_applier.py
# Applies to any company careers page using AI form filling
# Strategy:
#   1. Load the job listing page
#   2. AI scores the job
#   3. If score >= threshold, find the apply button and click it
#   4. AI fills the form (handles any ATS)
#   5. If CAPTCHA: pause + notify Tobi
#   6. If form too complex / blocked: notify Tobi with link to apply manually

import asyncio
from playwright.async_api import Page

from config.profile import PROFILE
from core.ai_scorer import score_job_fit, generate_full_cover_letter
from core.ai_form_filler import AIUniversalFormFiller
from core.captcha_handler import check_and_handle_captcha, detect_captcha
from utils.helpers import human_delay, scroll_slowly, is_excluded, truncate_text
from utils.logger import log_application, save_cover_letter
from utils.notifier import (
    notify_applied, notify_manual_apply_needed,
    notify_high_score_job, notify_error
)


# Apply button selectors — ordered by specificity
APPLY_BUTTON_SELECTORS = [
    'a:has-text("Easy Apply")',
    'button:has-text("Easy Apply")',
    'a:has-text("Apply now")',
    'button:has-text("Apply now")',
    'a:has-text("Apply for this job")',
    'button:has-text("Apply for this job")',
    'a:has-text("Apply for this position")',
    'a:has-text("Apply")',
    'button:has-text("Apply")',
    'button[data-control-name*="apply"]',
    'a[href*="apply"]',
    '[class*="apply-button"]',
    '[class*="apply_button"]',
    '[id*="apply-button"]',
    'input[value*="Apply"]',
]

# Signals that redirect to an external site (harder to auto-fill)
EXTERNAL_REDIRECT_SIGNALS = [
    "workday.com", "greenhouse.io", "lever.co", "taleo.net",
    "icims.com", "successfactors.com", "bamboohr.com",
    "jobvite.com", "smartrecruiters.com", "myworkdayjobs.com",
]


class UniversalApplier:
    """
    Applies to any job on any company careers site.
    Uses AI to fill forms, handles CAPTCHAs, notifies on manual intervention needed.
    """

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run
        self.applied_count = 0
        self.manual_needed = []

    async def apply_from_job_page(
        self,
        job_url: str,
        job_title: str,
        company: str,
        description: str = "",
        pre_scored: dict = None
    ) -> str:
        """
        Full apply flow for a single job.
        Returns: "applied" | "manual" | "skipped" | "failed"
        """
        # AI score (skip if already scored)
        if pre_scored:
            score_data = pre_scored
        else:
            print(f"  [AI] Scoring: {company} | {job_title}")
            score_data = score_job_fit(job_title, company, truncate_text(description))

        score = score_data.get("score", 5)
        reason = score_data.get("reason", "")
        red_flags = score_data.get("red_flags", [])

        # Skip if score too low
        if score < PROFILE["min_fit_score"]:
            log_application("company_site", company, job_title, "Dublin",
                            job_url, score, reason, "skipped",
                            notes=f"Red flags: {red_flags}")
            return "skipped"

        # Notify if very high score — worth manual attention too
        if score >= 9:
            await notify_high_score_job(company, job_title, score, job_url, reason)

        # Generate cover letter
        print(f"  [AI] Generating cover letter...")
        cover = generate_full_cover_letter(job_title, company, description)
        cover_path = save_cover_letter(company, job_title, cover)

        if self.dry_run:
            log_application("company_site", company, job_title, "Dublin",
                            job_url, score, reason, "dry_run", cover_path)
            print(f"  [◉] DRY RUN: {company} | {job_title} (score: {score})")
            return "dry_run"

        # Load job page if not already on it
        if self.page.url != job_url:
            try:
                await self.page.goto(job_url, wait_until="domcontentloaded")
                await human_delay(2000, 4000)
            except Exception as e:
                log_application("company_site", company, job_title, "Dublin",
                                job_url, score, reason, "failed", notes=str(e))
                return "failed"

        # CAPTCHA check on landing
        if await detect_captcha(self.page):
            solved = await check_and_handle_captcha(self.page, company, job_title, job_url)
            if not solved:
                await self._flag_manual(company, job_title, job_url, score, reason,
                                        cover_path, "CAPTCHA could not be solved")
                return "manual"

        # Find and click Apply button
        apply_clicked = await self._click_apply_button()

        if not apply_clicked:
            # No apply button found — might be a listing page, try direct navigation
            print(f"  [!] No apply button found for {company} | {job_title}")
            await self._flag_manual(company, job_title, job_url, score, reason,
                                    cover_path, "No apply button detected")
            return "manual"

        await human_delay(2000, 4000)

        # Check if we were redirected to an external ATS
        current_url = self.page.url
        is_external = any(signal in current_url for signal in EXTERNAL_REDIRECT_SIGNALS)

        if is_external and current_url != job_url:
            # Still try AI form filling on the redirected page
            print(f"  [→] Redirected to external ATS: {current_url[:60]}")

        # CAPTCHA check after clicking apply
        if await detect_captcha(self.page):
            solved = await check_and_handle_captcha(self.page, company, job_title, current_url)
            if not solved:
                await self._flag_manual(company, job_title, job_url, score, reason,
                                        cover_path, "CAPTCHA on apply page")
                return "manual"

        # AI fills the form
        filler = AIUniversalFormFiller(self.page, job_title, company, cover)
        success = await filler.fill_multi_page_form(max_steps=8)

        if success:
            self.applied_count += 1
            log_application("company_site", company, job_title, "Dublin",
                            job_url, score, reason, "applied", cover_path)
            await notify_applied(company, job_title, score, job_url)
            print(f"  [✓] Applied: {company} | {job_title} (score: {score})")
            return "applied"
        else:
            # Form incomplete — flag for manual
            await self._flag_manual(company, job_title, job_url, score, reason,
                                    cover_path, "Form submission incomplete")
            return "manual"

    async def _click_apply_button(self) -> bool:
        """Find and click the Apply button. Returns True if clicked."""
        for sel in APPLY_BUTTON_SELECTORS:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.scroll_into_view_if_needed()
                    await human_delay(300, 700)
                    await btn.click()
                    return True
            except Exception:
                pass
        return False

    async def _flag_manual(self, company: str, job_title: str, job_url: str,
                            score: int, reason: str, cover_path: str, flag_reason: str):
        """Log as needing manual apply and notify Tobi."""
        self.manual_needed.append({
            "company": company, "job_title": job_title, "url": job_url, "score": score
        })
        log_application("company_site", company, job_title, "Dublin",
                        job_url, score, reason, "manual_needed", cover_path,
                        notes=flag_reason)
        await notify_manual_apply_needed(company, job_title, job_url, flag_reason)
        print(f"  [→] Manual needed: {company} | {job_title} — {flag_reason}")
        print(f"      Link: {job_url}")

    async def scrape_and_apply_company(
        self,
        company: str,
        search_url: str,
        job_link_pattern: str = "",
        base_url: str = ""
    ):
        """
        Generic company site scraper + applier.
        Loads search_url, finds all job links, applies to each.
        """
        print(f"\n[{company}] Scraping: {search_url}")

        try:
            await self.page.goto(search_url, wait_until="domcontentloaded")
            await human_delay(2000, 4000)
            await scroll_slowly(self.page, 2000)
        except Exception as e:
            await notify_error(f"Scraping {company}", str(e))
            return

        # Find job links
        job_links = await self.page.evaluate(f"""() => {{
            const links = [];
            const anchors = document.querySelectorAll('a[href]');
            anchors.forEach(a => {{
                const href = a.href;
                const text = a.innerText.trim();
                const pattern = '{job_link_pattern}';
                if (
                    text.length > 5 && text.length < 150 &&
                    (pattern ? href.includes(pattern) : (
                        href.includes('job') || href.includes('position') ||
                        href.includes('career') || href.includes('vacancy') ||
                        href.includes('opening') || href.includes('role')
                    ))
                ) {{
                    links.push({{ text, href }});
                }}
            }});
            // Deduplicate
            const seen = new Set();
            return links.filter(l => {{
                if (seen.has(l.href)) return false;
                seen.add(l.href);
                return true;
            }}).slice(0, 30);
        }}""")

        print(f"  Found {len(job_links)} job links")

        for job in job_links:
            title = job["text"]
            url = job["href"]

            if is_excluded(title, PROFILE["excluded_keywords"]):
                continue

            # Ensure absolute URL
            if url.startswith("/"):
                url = (base_url or search_url.split("/")[0] + "//" + search_url.split("/")[2]) + url

            # Get description
            description = ""
            try:
                await self.page.goto(url, wait_until="domcontentloaded")
                await human_delay(1500, 3000)
                desc_el = await self.page.query_selector(
                    'main, article, [class*="description"], [class*="job-detail"], '
                    '[class*="content"], #content, .content'
                )
                if desc_el:
                    description = (await desc_el.inner_text())[:3000]
            except Exception:
                description = title  # Fallback — at least score on title

            result = await self.apply_from_job_page(url, title, company, description)
            await human_delay(3000, 7000)

            # Respect rate limits
            if self.applied_count % 5 == 0 and self.applied_count > 0:
                print(f"  [Pause] Applied to {self.applied_count} jobs — resting 30s...")
                await asyncio.sleep(30)
