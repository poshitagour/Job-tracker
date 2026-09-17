# core/scraper.py
# LinkedIn Easy Apply + Indeed scraper

import asyncio
import os
import random
from urllib.parse import urlencode, quote_plus
from playwright.async_api import async_playwright, Page, Browser

from config.profile import PROFILE, LINKEDIN_SEARCHES, INDEED_SEARCHES
from utils.helpers import (
    human_delay, human_type, human_click, scroll_slowly,
    safe_fill, safe_select, dismiss_modals, is_excluded, truncate_text
)
from core.ai_scorer import score_job_fit, generate_full_cover_letter, answer_application_question
from utils.logger import log_application, save_cover_letter


# ──────────────────────────────────────────────────────────────────────────────
# LINKEDIN
# ──────────────────────────────────────────────────────────────────────────────

class LinkedInBot:
    def __init__(self, page: Page, dry_run: bool = False, limit: int = 50):
        self.page = page
        self.dry_run = dry_run
        self.limit = limit
        self.applied_count = 0
        self.seen_urls = set()

    async def login(self):
        print("[LinkedIn] Logging in...")
        await self.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await human_delay(1000, 2000)

        await safe_fill(self.page, '#username', os.getenv("LINKEDIN_EMAIL"), "email")
        await human_delay(400, 800)
        await safe_fill(self.page, '#password', os.getenv("LINKEDIN_PASSWORD"), "password")
        await human_delay(600, 1200)
        await self.page.click('button[type="submit"]')
        await self.page.wait_for_load_state("domcontentloaded")
        await human_delay(2000, 4000)

        if "feed" in self.page.url or "checkpoint" in self.page.url:
            print("[LinkedIn] Logged in successfully.")
        else:
            print("[LinkedIn] WARNING: Login may have failed. Check manually.")

    async def search_and_apply(self):
        for search in LINKEDIN_SEARCHES:
            if self.applied_count >= self.limit:
                print(f"[LinkedIn] Hit limit of {self.limit} applications.")
                break

            print(f"\n[LinkedIn] Searching: '{search['keywords']}' in {search['location']}")
            await self._run_search(search)
            await human_delay(3000, 6000)

    async def _build_search_url(self, search: dict) -> str:
        params = {
            "keywords": search["keywords"],
            "location": search["location"],
            "f_AL": "true" if search.get("easy_apply") else "",  # Easy Apply filter
            "f_TPR": "r604800",  # Posted in last 7 days
            "f_E": "1,2",        # Entry level + Associate
            "sortBy": "DD",      # Most recent
        }
        return "https://www.linkedin.com/jobs/search/?" + urlencode({k: v for k, v in params.items() if v})

    async def _run_search(self, search: dict):
        url = await self._build_search_url(search)
        await self.page.goto(url, wait_until="domcontentloaded")
        await human_delay(2000, 4000)
        await dismiss_modals(self.page)

        # Collect job cards
        jobs = []
        for page_num in range(1, 6):  # Max 5 pages per search
            await scroll_slowly(self.page, 1500)
            await human_delay(1000, 2000)

            cards = await self.page.query_selector_all('.job-card-container, .jobs-search-results__list-item')
            print(f"  Found {len(cards)} job cards on page {page_num}")

            for card in cards:
                try:
                    title_el = await card.query_selector('.job-card-list__title, .job-card-container__link')
                    company_el = await card.query_selector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle')
                    link_el = await card.query_selector('a[href*="/jobs/view/"]')

                    title = (await title_el.inner_text()).strip() if title_el else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""
                    href = await link_el.get_attribute("href") if link_el else ""

                    if href and href not in self.seen_urls and title:
                        job_url = "https://www.linkedin.com" + href if href.startswith("/") else href
                        # Strip tracking params
                        job_url = job_url.split("?")[0]
                        jobs.append({"title": title, "company": company, "url": job_url})
                        self.seen_urls.add(href)
                except Exception:
                    pass

            # Next page
            try:
                next_btn = self.page.locator('button[aria-label="View next page"]')
                if await next_btn.is_visible(timeout=2000):
                    await next_btn.click()
                    await human_delay(2000, 4000)
                else:
                    break
            except Exception:
                break

        print(f"  Collected {len(jobs)} unique jobs for this search")

        # Process each job
        for job in jobs:
            if self.applied_count >= self.limit:
                break
            await self._process_job(job)
            await human_delay(2000, 5000)

    async def _process_job(self, job: dict):
        title = job["title"]
        company = job["company"]
        url = job["url"]

        # Quick pre-filter
        if is_excluded(title + " " + company, PROFILE["excluded_keywords"]):
            print(f"  [–] Excluded by keyword: {company} | {title}")
            return

        # Load job page
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await human_delay(1500, 3000)
            await dismiss_modals(self.page)
        except Exception as e:
            print(f"  [✗] Could not load job page: {e}")
            return

        # Get description
        description = ""
        try:
            desc_el = await self.page.query_selector('.jobs-description, .job-view-layout')
            if desc_el:
                description = (await desc_el.inner_text()).strip()
        except Exception:
            pass

        # AI scoring
        print(f"  [AI] Scoring: {company} | {title}")
        score_data = score_job_fit(title, company, truncate_text(description))
        score = score_data.get("score", 5)
        reason = score_data.get("reason", "")
        should_apply = score_data.get("apply", score >= PROFILE["min_fit_score"])

        if not should_apply:
            log_application("linkedin", company, title, "Dublin", url, score, reason, "skipped")
            return

        # Dry run
        if self.dry_run:
            log_application("linkedin", company, title, "Dublin", url, score, reason, "dry_run",
                            notes=f"Would apply | Red flags: {score_data.get('red_flags', [])}")
            return

        # Apply
        await self._apply_easy_apply(title, company, url, description, score, reason)

    async def _apply_easy_apply(self, title: str, company: str, url: str,
                                 description: str, score: int, reason: str):
        try:
            # Click Easy Apply button
            apply_btn = self.page.locator('button.jobs-apply-button, button:has-text("Easy Apply")').first
            if not await apply_btn.is_visible(timeout=3000):
                log_application("linkedin", company, title, "Dublin", url, score, reason, "skipped",
                                notes="No Easy Apply button")
                return

            await apply_btn.click()
            await human_delay(1500, 3000)

            # Generate cover letter before starting
            print(f"  [AI] Generating cover letter for {company}...")
            cover_letter = generate_full_cover_letter(title, company, description)
            cover_path = save_cover_letter(company, title, cover_letter)

            # Multi-step form loop
            step = 0
            max_steps = 10
            while step < max_steps:
                step += 1
                await human_delay(800, 1800)
                await dismiss_modals(self.page)

                # Fill current step
                await self._fill_form_step(title, company, cover_letter)

                # Check for Submit button
                submit_btn = self.page.locator('button[aria-label="Submit application"], button:has-text("Submit application")').first
                if await submit_btn.is_visible(timeout=1000):
                    await submit_btn.click()
                    await human_delay(2000, 4000)
                    self.applied_count += 1
                    log_application("linkedin", company, title, "Dublin", url,
                                    score, reason, "applied", cover_path)
                    print(f"  [✓] Applied! ({self.applied_count}/{self.limit})")
                    return

                # Next button
                next_btn = self.page.locator(
                    'button[aria-label="Continue to next step"], '
                    'button[aria-label="Review your application"], '
                    'button:has-text("Next"), '
                    'button:has-text("Review")'
                ).first
                if await next_btn.is_visible(timeout=1000):
                    await next_btn.click()
                    continue

                # If neither button found, we're stuck
                print(f"  [!] Form stuck at step {step} for {company}")
                break

            # Close modal if stuck
            try:
                dismiss = self.page.locator('button[aria-label="Dismiss"], button:has-text("Discard")').first
                if await dismiss.is_visible(timeout=1000):
                    await dismiss.click()
            except Exception:
                pass

            log_application("linkedin", company, title, "Dublin", url, score, reason, "failed",
                            notes=f"Stuck at step {step}")

        except Exception as e:
            log_application("linkedin", company, title, "Dublin", url, score, reason, "failed",
                            notes=str(e))
            print(f"  [✗] Application error: {e}")

    async def _fill_form_step(self, job_title: str, company: str, cover_letter: str):
        """Fill all visible fields on the current form step."""
        p = PROFILE

        # Phone
        for sel in ['input[id*="phone"], input[name*="phone"], input[placeholder*="phone"]']:
            try:
                el = self.page.locator(sel).first
                if await el.is_visible(timeout=500) and not await el.input_value():
                    await safe_fill(self.page, sel, p["phone"].replace("+353 ", ""), "phone")
            except Exception:
                pass

        # Cover letter textarea
        for sel in ['textarea[id*="cover"], textarea[name*="cover"], textarea[placeholder*="cover"]',
                    'textarea.jobs-easy-apply-form-section__field']:
            try:
                el = self.page.locator(sel).first
                if await el.is_visible(timeout=500):
                    current = await el.input_value()
                    if not current or len(current) < 50:
                        await safe_fill(self.page, sel, cover_letter, "cover letter")
            except Exception:
                pass

        # Text inputs — detect by label
        labels = await self.page.query_selector_all('label')
        for label in labels:
            try:
                label_text = (await label.inner_text()).strip().lower()
                for_attr = await label.get_attribute("for")
                if not for_attr:
                    continue

                input_sel = f'#{for_attr}'
                el = self.page.locator(input_sel).first

                if not await el.is_visible(timeout=300):
                    continue

                current_val = ""
                try:
                    current_val = await el.input_value()
                except Exception:
                    pass

                if current_val:
                    continue  # Already filled

                # Match label to answer
                value = self._match_label_to_answer(label_text, job_title, company)
                if value:
                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "select":
                        await safe_select(self.page, input_sel, value, label_text)
                    else:
                        await safe_fill(self.page, input_sel, value, label_text)

            except Exception:
                pass

        # Yes/No radio buttons
        await self._handle_radio_buttons()

        # Checkboxes (e.g., "I agree to terms")
        await self._handle_checkboxes()

    def _match_label_to_answer(self, label: str, job_title: str, company: str) -> str:
        """Map a form label to the right answer value."""
        p = PROFILE
        ca = p["common_answers"]

        mapping = {
            # Contact info
            "first name": p["preferred_name"],
            "last name": p["last_name"],
            "full name": f"{p['preferred_name']} {p['last_name']}",
            "email": p["email"],
            "phone": p["phone"],
            "mobile": p["phone"],
            "city": "Dublin",
            "location": "Dublin, Ireland",
            "linkedin": p["linkedin_url"],
            "github": p["github_url"],
            "portfolio": p["portfolio_url"],
            "website": p["portfolio_url"] or p["github_url"],

            # Work auth
            "authorized to work": "Yes",
            "right to work": "Yes",
            "work authorization": "Yes",
            "require sponsorship": "Yes",
            "visa sponsorship": "Yes",
            "require visa": "Yes",
            "work permit": "Yes",

            # Experience
            "years of experience": ca["years_of_experience_general"],
            "years experience": ca["years_of_experience_general"],
            "python": ca["years_of_experience_python"],
            "java": ca["years_of_experience_java"],
            "sql": ca["years_of_experience_sql"],
            "javascript": ca["years_of_experience_javascript"],

            # Education
            "degree": "Master's",
            "highest education": "Master's Degree",
            "university": p["current_university"],
            "graduation year": p["current_grad_year"],
            "gpa": "3.8",

            # Salary
            "salary": ca["salary_expectation"],
            "expected salary": ca["salary_expectation"],
            "salary expectation": ca["salary_expectation"],

            # Availability
            "start date": ca["available_start_date"],
            "notice period": "2 weeks",
            "available": ca["available_start_date"],

            # Preferences
            "remote": "Hybrid",
            "office": "Hybrid",
            "willing to relocate": "No",
            "relocate": "No",

            # Diversity (optional)
            "gender": ca["gender"],
            "ethnicity": ca["ethnicity"],
            "disability": ca["disability"],
            "veteran": ca["veteran"],
            "race": "Prefer not to say",
        }

        for key, value in mapping.items():
            if key in label:
                return value

        return ""

    async def _handle_radio_buttons(self):
        """Auto-select Yes/No radio buttons based on context."""
        radio_groups = await self.page.query_selector_all('fieldset')
        for group in radio_groups:
            try:
                legend = await group.query_selector('legend')
                if not legend:
                    continue
                legend_text = (await legend.inner_text()).strip().lower()

                # Default logic
                if any(k in legend_text for k in ["authorized", "right to work", "legally"]):
                    yes_radio = group.locator('input[type="radio"][value*="yes" i], input[type="radio"] + label:has-text("Yes")')
                    await yes_radio.first.click()
                elif any(k in legend_text for k in ["require sponsor", "need sponsor", "visa sponsor"]):
                    yes_radio = group.locator('input[type="radio"][value*="yes" i]')
                    await yes_radio.first.click()
                elif any(k in legend_text for k in ["relocate", "willing to move"]):
                    no_radio = group.locator('input[type="radio"][value*="no" i]')
                    await no_radio.first.click()
            except Exception:
                pass

    async def _handle_checkboxes(self):
        """Handle checkboxes — tick agreement checkboxes."""
        checkboxes = await self.page.query_selector_all('input[type="checkbox"]')
        for cb in checkboxes:
            try:
                is_checked = await cb.is_checked()
                label_el = await cb.evaluate_handle("el => el.labels ? el.labels[0] : null")
                label_text = ""
                if label_el:
                    label_text = (await label_el.inner_text()).lower()

                # Agree to terms/privacy
                if not is_checked and any(k in label_text for k in ["agree", "terms", "privacy", "consent"]):
                    await cb.click()
                    await human_delay(200, 400)
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# INDEED
# ──────────────────────────────────────────────────────────────────────────────

class IndeedBot:
    def __init__(self, page: Page, dry_run: bool = False, limit: int = 30):
        self.page = page
        self.dry_run = dry_run
        self.limit = limit
        self.applied_count = 0
        self.seen_urls = set()

    async def search_and_collect(self):
        """
        Indeed is harder to auto-apply (most redirect to company sites).
        This scrapes job listings and logs them for manual review,
        or applies via Indeed's native apply flow where available.
        """
        all_jobs = []

        for search in INDEED_SEARCHES:
            print(f"\n[Indeed] Searching: '{search['keywords']}' in {search['location']}")
            jobs = await self._scrape_search(search)
            all_jobs.extend(jobs)
            await human_delay(3000, 6000)

        print(f"\n[Indeed] Total jobs scraped: {len(all_jobs)}")

        for job in all_jobs:
            if self.applied_count >= self.limit:
                break
            await self._process_job(job)
            await human_delay(2000, 5000)

    async def _scrape_search(self, search: dict) -> list:
        kw = quote_plus(search["keywords"])
        loc = quote_plus(search["location"])
        url = f"https://ie.indeed.com/jobs?q={kw}&l={loc}&fromage=7&sort=date"

        await self.page.goto(url, wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        jobs = []
        for page_num in range(1, 4):  # Max 3 pages
            await scroll_slowly(self.page, 2000)
            await human_delay(1000, 2000)

            cards = await self.page.query_selector_all('[data-jk], .job_seen_beacon')
            for card in cards:
                try:
                    jk = await card.get_attribute("data-jk")
                    title_el = await card.query_selector('h2.jobTitle span, [data-testid="job-title"]')
                    company_el = await card.query_selector('[data-testid="company-name"], .companyName')

                    title = (await title_el.inner_text()).strip() if title_el else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""

                    if jk and jk not in self.seen_urls and title:
                        job_url = f"https://ie.indeed.com/viewjob?jk={jk}"
                        jobs.append({"title": title, "company": company, "url": job_url, "jk": jk})
                        self.seen_urls.add(jk)
                except Exception:
                    pass

            # Next page
            try:
                next_btn = self.page.locator('a[aria-label="Next Page"], a[data-testid="pagination-page-next"]')
                if await next_btn.is_visible(timeout=2000):
                    await next_btn.click()
                    await human_delay(2000, 4000)
                else:
                    break
            except Exception:
                break

        print(f"  Collected {len(jobs)} jobs")
        return jobs

    async def _process_job(self, job: dict):
        title = job["title"]
        company = job["company"]
        url = job["url"]

        if is_excluded(title, PROFILE["excluded_keywords"]):
            return

        # Load job
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await human_delay(1500, 3000)
        except Exception:
            return

        # Get description
        description = ""
        try:
            desc_el = await self.page.query_selector('#jobDescriptionText, .jobsearch-JobComponent-description')
            if desc_el:
                description = (await desc_el.inner_text()).strip()
        except Exception:
            pass

        # AI score
        score_data = score_job_fit(title, company, truncate_text(description))
        score = score_data.get("score", 5)
        reason = score_data.get("reason", "")
        should_apply = score_data.get("apply", score >= PROFILE["min_fit_score"])

        if not should_apply:
            log_application("indeed", company, title, "Dublin", url, score, reason, "skipped")
            return

        if self.dry_run:
            log_application("indeed", company, title, "Dublin", url, score, reason, "dry_run")
            return

        # Check if Indeed Apply (native) is available
        try:
            apply_btn = self.page.locator('button#indeedApplyButton, button:has-text("Apply now")').first
            if await apply_btn.is_visible(timeout=2000):
                # Log for manual apply — Indeed native apply varies too much
                log_application("indeed", company, title, "Dublin", url, score, reason, "skipped",
                                notes="Indeed native apply — visit manually: " + url)
                print(f"  [→] Indeed: {company} | {title} — visit manually (score: {score})")
            else:
                log_application("indeed", company, title, "Dublin", url, score, reason, "skipped",
                                notes="External apply — redirects to company site")
        except Exception as e:
            log_application("indeed", company, title, "Dublin", url, score, reason, "failed", notes=str(e))
