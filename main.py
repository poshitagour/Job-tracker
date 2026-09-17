# main.py -- entry point

import asyncio
import argparse
import os
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

from core.scraper import LinkedInBot, IndeedBot
from core.company_scrapers import CompanySiteOrchestrator
from core.irish_scraper import IndeedIEBot, IrishJobsBot
from utils.logger import print_session_summary

_HEADLESS_SHELL = "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"


def parse_args():
    parser = argparse.ArgumentParser(description="Tobi's Job Application Bot")
    parser.add_argument("--platform",
                        choices=["linkedin", "indeed", "company", "irishjobs", "indeed_ie", "all"],
                        default="linkedin", help="Platform(s) to run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and score but do not submit")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max applications per session (default: 20)")
    parser.add_argument("--headless", action="store_true",
                        help="Headless browser (default: visible)")
    parser.add_argument("--talent-communities", action="store_true",
                        help="Join talent/graduate communities at key companies")
    return parser.parse_args()


async def run(args):
    print("\n" + "=" * 55)
    print("  Poshita Gour - Ireland Stamp 1G Job Tracker")
    print(f"  Platform : {args.platform.upper()}")
    print(f"  Mode     : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  Limit    : {args.limit}")
    print("=" * 55 + "\n")

    needs_anthropic = args.platform in ["linkedin", "indeed", "company", "all"]
    needs_linkedin  = args.platform in ["linkedin", "all"]

    if needs_anthropic and not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set in .env"); return
    if needs_linkedin and not os.getenv("LINKEDIN_EMAIL"):
        print("ERROR: LINKEDIN_EMAIL not set in .env"); return

    launch_opts = {
        "user_data_dir": "./browser_session",
        "headless": args.headless,
        "viewport": {"width": 1280, "height": 800},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    if os.path.exists(_HEADLESS_SHELL):
        launch_opts["executable_path"] = _HEADLESS_SHELL

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(**launch_opts)
        page = await context.new_page()

        try:
            if args.platform in ["linkedin", "all"]:
                bot = LinkedInBot(page, dry_run=args.dry_run, limit=args.limit)
                await bot.login()
                await bot.search_and_apply()

            if args.platform in ["indeed", "all"]:
                ibot = IndeedBot(page, dry_run=args.dry_run, limit=min(args.limit, 20))
                await ibot.search_and_collect()

            if args.platform in ["company", "all"]:
                cbot = CompanySiteOrchestrator(page, dry_run=args.dry_run)
                if args.talent_communities:
                    await cbot.join_talent_communities()
                await cbot.run_all()

            if args.platform in ["indeed_ie", "irishjobs", "all"]:
                iebot = IndeedIEBot(page, dry_run=args.dry_run)
                await iebot.run_all_searches()

            if args.platform in ["irishjobs", "all"]:
                ijbot = IrishJobsBot(page, dry_run=args.dry_run)
                await ijbot.run_all_searches()

        except KeyboardInterrupt:
            print("\n[Bot] Stopped by user.")
        except Exception as e:
            print(f"\n[Bot] Error: {e}")
            import traceback; traceback.print_exc()
        finally:
            await context.close()

    print_session_summary()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
