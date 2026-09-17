# core/company_scrapers.py
# Direct company career site scrapers
# Each ATS platform (Greenhouse, Lever, Workday, Taleo) has one scraper
# Individual company scrapers handle unique flows

import asyncio
from playwright.async_api import Page
from urllib.parse import urlencode, quote_plus

from config.profile import PROFILE
from core.ai_scorer import score_job_fit, generate_full_cover_letter
from core.form_filler import SmartFormFiller, fill_fidelity_talent_community
from utils.helpers import human_delay, scroll_slowly, dismiss_modals, is_excluded, truncate_text
from utils.logger import log_application, save_cover_letter


# ── Target company career URLs ─────────────────────────────────────
COMPANY_CAREER_SITES = [
    # Format: (company_name, careers_url, ats_type)
    # ATS types: greenhouse, lever, workday, taleo, custom
    ("Accenture Ireland",   "https://www.accenture.com/ie-en/careers/jobsearch?jt=0&sb=0&pg=1&ct=dublin&fs=1&jk=graduate&is=1", "taleo"),
    ("Version 1",           "https://www.version1.com/careers/current-vacancies/?filter=graduate", "custom"),
    ("Fidelity Ireland",    "https://jobs.fidelity.com/ie/jobs/?keyword=graduate+software", "custom"),
    ("HubSpot",             "https://www.hubspot.com/jobs/search#t=All&p=1&q=graduate%20engineer%20dublin", "greenhouse"),
    ("Salesforce",          "https://careers.salesforce.com/en/jobs/?search=associate+software+engineer&location=Dublin", "custom"),
    ("Workday",             "https://www.workday.com/en-us/company/careers/overview.html", "workday"),
    ("Intercom",            "https://www.intercom.com/careers#open-roles", "greenhouse"),
    ("Guidewire",           "https://www.guidewire.com/company/careers?location=Dublin", "greenhouse"),
    ("DraftKings",          "https://careers.draftkings.com/jobs?location=Dublin", "greenhouse"),
    ("BearingPoint",        "https://www.bearingpoint.com/en-ie/careers/students-graduates/", "custom"),
    ("MongoDB",             "https://www.mongodb.com/careers/departments/campus", "greenhouse"),
    ("Tines",               "https://www.tines.com/careers#open-roles", "greenhouse"),
    ("Zendesk",             "https://jobs.zendesk.com/us/en/search-results?keywords=graduate&location=Dublin", "workday"),
    ("New Relic",           "https://newrelic.com/about/careers?q=graduate&location=Dublin", "greenhouse"),
    ("Datadog",             "https://careers.datadoghq.com/all-jobs/?location=Dublin&q=graduate", "greenhouse"),
]


# ──────────────────────────────────────────────────────────────────────────────
# GENERIC ATS SCRAPERS
# ──────────────────────────────────────────────────────────────────────────────

class GreenhouseBot:
    """
    Handles Greenhouse ATS (used by HubSpot, Intercom, MongoDB, DraftKings, Tines, etc.)
    Greenhouse forms are relatively standardized.
    """
    def __init__(self, page: Page, company: str, dry_run: bool = False):
        self.page = page
        self.company = company
        self.dry_run = dry_run

    async def apply_to_job(self, job_url: str, job_title: str, description: str,
                            score: int, reason: str):
        if self.dry_run:
            log_application("company_site", self.company, job_title, "Dublin",
                            job_url, score, reason, "dry_run")
            return

        # Generate cover letter
        cover = generate_full_cover_letter(job_title, self.company, description)
        cover_path = save_cover_letter(self.company, job_title, cover)

        await self.page.goto(job_url, wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        # Click Apply button
        try:
            apply_btn = self.page.locator('a:has-text("Apply for this Job"), a:has-text("Apply Now"), button:has-text("Apply")').first
            if await apply_btn.is_visible(timeout=3000):
                await apply_btn.click()
                await human_delay(1500, 3000)
        except Exception:
            pass

        # Fill form
        filler = SmartFormFiller(self.page, PROFILE, job_title, self.company, cover)
        await filler.fill_all_visible_fields()
        await human_delay(1000, 2000)

        # Submit
        try:
            submit = self.page.locator('input[type="submit"], button[type="submit"], button:has-text("Submit Application")').first
            if await submit.is_visible(timeout=2000):
                await submit.click()
                await human_delay(2000, 4000)
                log_application("company_site", self.company, job_title, "Dublin",
                                job_url, score, reason, "applied", cover_path)
                print(f"  [✓] Applied via Greenhouse: {self.company} | {job_title}")
                return
        except Exception as e:
            pass

        log_application("company_site", self.company, job_title, "Dublin",
                        job_url, score, reason, "failed", notes="Could not submit")


class LeverBot:
    """
    Handles Lever ATS. Lever has a cleaner, more consistent form structure.
    """
    def __init__(self, page: Page, company: str, dry_run: bool = False):
        self.page = page
        self.company = company
        self.dry_run = dry_run

    async def apply_to_job(self, job_url: str, job_title: str, description: str,
                            score: int, reason: str):
        if self.dry_run:
            log_application("company_site", self.company, job_title, "Dublin",
                            job_url, score, reason, "dry_run")
            return

        cover = generate_full_cover_letter(job_title, self.company, description)
        cover_path = save_cover_letter(self.company, job_title, cover)

        await self.page.goto(job_url, wait_until="domcontentloaded")
        await human_delay(2000, 3000)

        filler = SmartFormFiller(self.page, PROFILE, job_title, self.company, cover)
        await filler.fill_all_visible_fields()
        await human_delay(1000, 2000)

        try:
            submit = self.page.locator('button:has-text("Submit application"), button[type="submit"]').first
            if await submit.is_visible(timeout=2000):
                await submit.click()
                await human_delay(2000, 4000)
                log_application("company_site", self.company, job_title, "Dublin",
                                job_url, score, reason, "applied", cover_path)
                print(f"  [✓] Applied via Lever: {self.company} | {job_title}")
                return
        except Exception:
            pass

        log_application("company_site", self.company, job_title, "Dublin",
                        job_url, score, reason, "failed")


class WorkdayBot:
    """
    Workday ATS — used by Workday itself, Zendesk, and others.
    Workday is complex with multi-step flows and heavy JS.
    This handles the job listing scrape + flags for manual apply.
    """
    def __init__(self, page: Page, company: str, dry_run: bool = False):
        self.page = page
        self.company = company
        self.dry_run = dry_run

    async def scrape_jobs(self, search_url: str) -> list:
        jobs = []
        await self.page.goto(search_url, wait_until="networkidle")
        await human_delay(3000, 5000)

        cards = await self.page.query_selector_all('[data-automation-id="jobTitle"], .css-1q2dra3')
        for card in cards:
            try:
                title = (await card.inner_text()).strip()
                link = await card.query_selector('a')
                href = await link.get_attribute("href") if link else ""
                if title and href:
                    jobs.append({"title": title, "url": href, "company": self.company})
            except Exception:
                pass

        return jobs


# ──────────────────────────────────────────────────────────────────────────────
# COMPANY-SPECIFIC SCRAPERS
# ──────────────────────────────────────────────────────────────────────────────

class FidelityBot:
    """
    Fidelity Ireland — jobs.fidelity.com/ie/
    Also handles talentcommunity.fidelity.com for graduate programmes.
    """
    JOBS_URL = "https://jobs.fidelity.com/ie/jobs/"
    TALENT_COMMUNITY_URL = "https://talentcommunity.fidelity.com/flows/tc-ireland"

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run

    async def join_talent_community(self):
        """Fill out Fidelity's talent community form to get on their radar."""
        print("[Fidelity] Joining talent community...")
        await self.page.goto(self.TALENT_COMMUNITY_URL, wait_until="domcontentloaded")
        await human_delay(2000, 4000)

        await fill_fidelity_talent_community(self.page, PROFILE)

        # Submit
        if not self.dry_run:
            try:
                submit = self.page.locator('button[type="submit"], button:has-text("Submit"), button:has-text("Join")').first
                if await submit.is_visible(timeout=3000):
                    await submit.click()
                    await human_delay(2000, 4000)
                    print("  [✓] Joined Fidelity talent community")
            except Exception as e:
                print(f"  [!] Could not submit Fidelity form: {e}")

    async def scrape_and_apply(self):
        print("[Fidelity] Scraping jobs...")
        await self.page.goto(self.JOBS_URL + "?keyword=graduate+software+engineer", wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        jobs = []
        cards = await self.page.query_selector_all('[class*="job-result"], article, [class*="job-listing"]')
        for card in cards:
            try:
                title_el = await card.query_selector('h2, h3, [class*="title"]')
                link_el = await card.query_selector('a')
                title = (await title_el.inner_text()).strip() if title_el else ""
                href = await link_el.get_attribute("href") if link_el else ""
                if title and href:
                    url = href if href.startswith("http") else "https://jobs.fidelity.com" + href
                    jobs.append({"title": title, "url": url})
            except Exception:
                pass

        print(f"  Found {len(jobs)} Fidelity jobs")
        for job in jobs:
            if is_excluded(job["title"], PROFILE["excluded_keywords"]):
                continue
            # Log for manual review — Fidelity's apply flow is complex
            log_application("company_site", "Fidelity", job["title"], "Dublin",
                            job["url"], 8, "Target company, relevant role", "dry_run",
                            notes="Visit manually to apply: " + job["url"])
            print(f"  [→] Fidelity: {job['title']} — {job['url']}")


class AccentureBot:
    """
    Accenture Ireland — uses Taleo ATS.
    Scrapes graduate roles and fills Taleo forms.
    """
    SEARCH_URL = "https://www.accenture.com/ie-en/careers/jobsearch?jt=0&ct=dublin&fs=1&jk=graduate+technology&is=1"

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run

    async def scrape_and_log(self):
        print("[Accenture] Scraping graduate roles...")
        await self.page.goto(self.SEARCH_URL, wait_until="domcontentloaded")
        await human_delay(2000, 4000)
        await scroll_slowly(self.page, 2000)

        jobs = []
        cards = await self.page.query_selector_all('[class*="job-listing"], [class*="cmp-job"], article')
        for card in cards:
            try:
                title_el = await card.query_selector('h2, h3, [class*="title"], a')
                link_el = await card.query_selector('a')
                title = (await title_el.inner_text()).strip() if title_el else ""
                href = await link_el.get_attribute("href") if link_el else ""
                if title and href:
                    url = href if href.startswith("http") else "https://www.accenture.com" + href
                    if not is_excluded(title, PROFILE["excluded_keywords"]):
                        jobs.append({"title": title, "url": url})
            except Exception:
                pass

        print(f"  Found {len(jobs)} Accenture roles")
        for job in jobs:
            log_application("company_site", "Accenture", job["title"], "Dublin",
                            job["url"], 8, "Tier 1 target — CSEP Trusted Partner", "dry_run",
                            notes="Apply directly: " + job["url"])
            print(f"  [→] Accenture: {job['title']}")


class Version1Bot:
    """Version 1 Ireland — custom careers site."""
    SEARCH_URL = "https://www.version1.com/careers/current-vacancies/"

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run

    async def scrape_and_log(self):
        print("[Version 1] Scraping roles...")
        await self.page.goto(self.SEARCH_URL, wait_until="domcontentloaded")
        await human_delay(2000, 3500)

        jobs = []
        links = await self.page.query_selector_all('a[href*="vacancy"], a[href*="job"], [class*="vacancy"] a, [class*="job"] a')
        for link in links:
            try:
                title = (await link.inner_text()).strip()
                href = await link.get_attribute("href")
                if title and href and len(title) > 5:
                    url = href if href.startswith("http") else "https://www.version1.com" + href
                    if not is_excluded(title, PROFILE["excluded_keywords"]):
                        jobs.append({"title": title, "url": url})
            except Exception:
                pass

        # Deduplicate
        seen = set()
        unique_jobs = []
        for job in jobs:
            if job["url"] not in seen:
                seen.add(job["url"])
                unique_jobs.append(job)

        print(f"  Found {len(unique_jobs)} Version 1 roles")
        for job in unique_jobs:
            log_application("company_site", "Version 1", job["title"], "Dublin",
                            job["url"], 8, "Tier 1 Irish IT consultancy", "dry_run",
                            notes="Apply directly: " + job["url"])
            print(f"  [→] Version 1: {job['title']}")


# ──────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ──────────────────────────────────────────────────────────────────────────────

class CompanySiteOrchestrator:
    """Runs all company site scrapers."""

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run

    async def run_all(self):
        print("\n[Company Sites] Starting direct company site scraping...")

        runners = [
            FidelityBot(self.page, self.dry_run).scrape_and_apply,
            AccentureBot(self.page, self.dry_run).scrape_and_log,
            Version1Bot(self.page, self.dry_run).scrape_and_log,
        ]

        for runner in runners:
            try:
                await runner()
                await human_delay(3000, 6000)
            except Exception as e:
                print(f"  [!] Error in company scraper: {e}")

    async def join_talent_communities(self):
        """Join talent/graduate pipelines at key companies."""
        print("\n[Talent Communities] Registering interest...")
        try:
            await FidelityBot(self.page, self.dry_run).join_talent_community()
            await human_delay(3000, 5000)
        except Exception as e:
            print(f"  [!] Fidelity talent community error: {e}")
