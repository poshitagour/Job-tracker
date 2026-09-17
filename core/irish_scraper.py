# core/irish_scraper.py
# Irish niche job scraping: ie.indeed.com + irishjobs.ie
# Sends Telegram alerts with fit scores and CV recommendations.
# Deduplicates against seen_jobs.json so alerts never repeat across runs.

import asyncio
from datetime import date
from urllib.parse import quote_plus
from playwright.async_api import Page

from config.profile import INDEED_IE_SEARCHES, IRISHJOBS_SEARCHES, PROFILE
from core.job_scorer import calculate_fit_score, get_cv_recommendation, get_company_flags, get_job_triage
from utils.deduplicator import is_seen, mark_seen, record_duplicate
from utils.notifier import notify_new_job_alert
from utils.logger import log_application
from utils.helpers import human_delay, scroll_slowly, is_excluded, truncate_text

FIT_THRESHOLD = PROFILE.get("min_fit_score", 60)  # Only alert on jobs at or above this score


# ───────────────────────────────────────────────────────────────────────────────
# INDEED IRELAND
# ───────────────────────────────────────────────────────────────────────────────

class IndeedIEBot:
    """Scrapes ie.indeed.com for Irish niche searches."""

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run
        self._seen_jks: set = set()
        self.stats = {"found": 0, "alerted": 0, "skipped": 0, "duplicates": 0}

    async def run_all_searches(self) -> dict:
        print("\n[Indeed IE] Starting Irish niche searches...")
        for search in INDEED_IE_SEARCHES:
            kw, loc = search["keywords"], search["location"]
            print(f"\n[Indeed IE] '{kw}' in {loc}")
            jobs = await self._scrape_search(kw, loc)
            for job in jobs:
                await self._process_job(job, "Indeed IE")
                await human_delay(800, 2000)
            await human_delay(3000, 5000)

        print(
            f"\n[Indeed IE] Done. "
            f"Found: {self.stats['found']}  "
            f"Alerted: {self.stats['alerted']}  "
            f"Dupes: {self.stats['duplicates']}  "
            f"Below threshold: {self.stats['skipped']}"
        )
        return self.stats

    async def _scrape_search(self, keywords: str, location: str) -> list:
        kw = quote_plus(keywords)
        loc = quote_plus(location)
        url = f"https://ie.indeed.com/jobs?q={kw}&l={loc}&fromage=14&sort=date"

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2000, 4000)
        except Exception as e:
            print(f"  [!] Could not load Indeed IE: {e}")
            return []

        jobs = []
        for _ in range(2):  # max 2 pages
            await scroll_slowly(self.page, 2000)
            await human_delay(800, 1500)

            cards = await self.page.query_selector_all('[data-jk], .job_seen_beacon')
            for card in cards:
                try:
                    jk = await card.get_attribute("data-jk")
                    if not jk or jk in self._seen_jks:
                        continue

                    title_el = await card.query_selector(
                        'h2.jobTitle span, [data-testid="job-title"] span, h2.jobTitle a'
                    )
                    company_el = await card.query_selector(
                        '[data-testid="company-name"], .companyName'
                    )
                    loc_el = await card.query_selector(
                        '[data-testid="text-location"], .companyLocation'
                    )
                    date_el = await card.query_selector(
                        '[data-testid="myJobsStateDate"], .date, .result-link-bar-container span'
                    )

                    title   = (await title_el.inner_text()).strip()   if title_el   else ""
                    company = (await company_el.inner_text()).strip() if company_el else ""
                    loc_txt = (await loc_el.inner_text()).strip()     if loc_el     else location
                    posted  = (await date_el.inner_text()).strip()    if date_el    else str(date.today())

                    if title:
                        jobs.append({
                            "title": title, "company": company,
                            "location": loc_txt, "posted": posted,
                            "url": f"https://ie.indeed.com/viewjob?jk={jk}",
                            "jk": jk,
                        })
                        self._seen_jks.add(jk)
                except Exception:
                    pass

            try:
                nxt = self.page.locator(
                    'a[aria-label="Next Page"], a[data-testid="pagination-page-next"]'
                )
                if await nxt.is_visible(timeout=2000):
                    await nxt.click()
                    await human_delay(2000, 4000)
                else:
                    break
            except Exception:
                break

        print(f"  Collected {len(jobs)} jobs")
        return jobs

    async def _process_job(self, job: dict, source: str):
        title, company, url = job["title"], job["company"], job["url"]
        location = job.get("location", "Ireland")
        posted   = job.get("posted",   str(date.today()))

        if is_excluded(title, PROFILE["excluded_keywords"]):
            return

        self.stats["found"] += 1

        if is_seen(url, title, company):
            record_duplicate()
            self.stats["duplicates"] += 1
            print(f"  [=] Already seen: {company} | {title}")
            return

        description = await self._fetch_description(url)
        triage = get_job_triage(title, description, company)
        score, cv_rec, flags = triage["fit_score"], triage["cv_rec"], triage["flags"]

        log_application(
            source.lower().replace(" ", "_"),
            company, title, location, url,
            score, f"{score}/100 | {cv_rec}",
            "dry_run" if self.dry_run else "alerted" if score >= FIT_THRESHOLD else "skipped",
            notes=(f"CV: {cv_rec} | Permit: {triage['permit_path']} | Tier: {triage['company_tier']} | "
                    f"PermitReason: {triage['permit_reason']}" + (f" | {', '.join(flags)}" if flags else "")),
        )

        if score < FIT_THRESHOLD:
            self.stats["skipped"] += 1
            print(f"  [-] {score}/100 (below {FIT_THRESHOLD}): {company} | {title}")
            return

        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  [*] {score}/100{flag_str}: {company} | {title} | {cv_rec}")

        await notify_new_job_alert(
            title=title, company=company, location=location,
            score=score, cv_rec=cv_rec, url=url,
            posted=posted, source=source, flags=flags,
        )
        mark_seen(url, title, company, alerted=True)
        self.stats["alerted"] += 1

    async def _fetch_description(self, url: str) -> str:
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await human_delay(800, 1500)
            el = await self.page.query_selector(
                '#jobDescriptionText, .jobsearch-JobComponent-description'
            )
            if el:
                return truncate_text((await el.inner_text()).strip())
        except Exception:
            pass
        return ""


# ───────────────────────────────────────────────────────────────────────────────
# IRISHJOBS.IE
# ───────────────────────────────────────────────────────────────────────────────

class IrishJobsBot:
    """Scrapes irishjobs.ie for data/analytics roles."""

    BASE = "https://www.irishjobs.ie"

    def __init__(self, page: Page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run
        self._seen: set = set()
        self.stats = {"found": 0, "alerted": 0, "skipped": 0, "duplicates": 0}

    async def run_all_searches(self) -> dict:
        print("\n[IrishJobs] Starting irishjobs.ie searches...")
        for search in IRISHJOBS_SEARCHES:
            kw, loc = search["keywords"], search["location"]
            print(f"\n[IrishJobs] '{kw}' in {loc}")
            jobs = await self._scrape_search(kw, loc)
            for job in jobs:
                await self._process_job(job)
                await human_delay(800, 2000)
            await human_delay(3000, 5000)

        print(
            f"\n[IrishJobs] Done. "
            f"Found: {self.stats['found']}  "
            f"Alerted: {self.stats['alerted']}  "
            f"Dupes: {self.stats['duplicates']}"
        )
        return self.stats

    async def _scrape_search(self, keywords: str, location: str) -> list:
        kw  = quote_plus(keywords)
        loc = quote_plus(location)
        url = f"{self.BASE}/ShowResults.aspx?Keywords={kw}&Location=1&SectorId=0&JobType=0&JobTitle=0&language=0&Recruiter=Company&RadiusFrom=0&NextRow=0"

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(2000, 4000)
        except Exception as e:
            print(f"  [!] Could not load IrishJobs: {e}")
            return []

        jobs = []
        cards = await self.page.query_selector_all(
            '.job-listing, .IJ_JobListing, article[class*="job"], '
            '[class*="job-item"], div[id*="job_"] '
        )

        for card in cards:
            try:
                title_el   = await card.query_selector('h2 a, h3 a, .IJ_JobTitle a, [class*="title"] a')
                company_el = await card.query_selector('.IJ_Company, .company-name, [class*="company"]')
                loc_el     = await card.query_selector('.IJ_Location, .location, [class*="location"]')

                title   = (await title_el.inner_text()).strip()   if title_el   else ""
                company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                loc_txt = (await loc_el.inner_text()).strip()     if loc_el     else location
                href    = await title_el.get_attribute("href")    if title_el   else ""

                if not href:
                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else ""

                if title and href:
                    job_url = href if href.startswith("http") else self.BASE + href
                    key = title + href
                    if key not in self._seen:
                        jobs.append({
                            "title": title, "company": company,
                            "location": loc_txt, "url": job_url,
                            "posted": str(date.today()),
                        })
                        self._seen.add(key)
            except Exception:
                pass

        print(f"  Collected {len(jobs)} jobs")
        return jobs

    async def _process_job(self, job: dict):
        title, company, url = job["title"], job["company"], job["url"]
        location = job.get("location", "Ireland")
        posted   = job.get("posted",   str(date.today()))

        if is_excluded(title, PROFILE["excluded_keywords"]):
            return

        self.stats["found"] += 1

        if is_seen(url, title, company):
            record_duplicate()
            self.stats["duplicates"] += 1
            print(f"  [=] Already seen: {company} | {title}")
            return

        description = ""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await human_delay(800, 1500)
            el = await self.page.query_selector(
                '.job-description, .IJ_JobDescription, [class*="description"]'
            )
            if el:
                description = truncate_text((await el.inner_text()).strip())
        except Exception:
            pass

        triage = get_job_triage(title, description, company)
        score, cv_rec, flags = triage["fit_score"], triage["cv_rec"], triage["flags"]

        log_application(
            "irishjobs",
            company, title, location, url,
            score, f"{score}/100 | {cv_rec}",
            "dry_run" if self.dry_run else "alerted" if score >= FIT_THRESHOLD else "skipped",
            notes=(f"CV: {cv_rec} | Permit: {triage['permit_path']} | Tier: {triage['company_tier']} | "
                    f"PermitReason: {triage['permit_reason']}" + (f" | {', '.join(flags)}" if flags else "")),
        )

        if score < FIT_THRESHOLD:
            self.stats["skipped"] += 1
            print(f"  [-] {score}/100 (below {FIT_THRESHOLD}): {company} | {title}")
            return

        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  [*] {score}/100{flag_str}: {company} | {title} | {cv_rec}")

        await notify_new_job_alert(
            title=title, company=company, location=location,
            score=score, cv_rec=cv_rec, url=url,
            posted=posted, source="IrishJobs", flags=flags,
        )
        mark_seen(url, title, company, alerted=True)
        self.stats["alerted"] += 1
