"""
scraper.py — Naukri job scraper using Playwright.

Fixes applied vs. original:
  - FIX #1  : clean_job_description() removed; imported from utils.py (DRY)
  - FIX #2  : Credentials read from .env via python-dotenv, NOT from sys.argv
              (argv credentials were visible to all OS users in process list)
  - FIX #3  : Specific exception types used; bare except: replaced everywhere
  - FIX #4  : Deduplication set loaded at startup — no duplicate rows on repeat runs
  - FIX #5  : Random human-like delays already present; kept and documented
  - FIX #6  : Job cards already extracted from single parent element (no misalignment)
  - FIX #7  : Body text now targets the JD container first, falls back to <body>
"""

import asyncio
import csv
import os
import random
import sys

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# FIX #1: Import shared helper instead of duplicating it
from utils import clean_job_description, logger

# Force UTF-8 on Windows terminals
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


async def scrape_naukri(
    job_title: str,
    location: str = "",
    experience: str = "0",
    max_jobs: int = 100,
    username: str = "",
    password: str = "",
) -> None:
    # FIX #2: Credentials fallback — prefer .env over argv so secrets stay out
    # of the OS process list. The UI can still pass them for the first-run login.
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    load_dotenv(os.path.join(root_dir, ".env"))
    if not username:
        username = os.getenv("NAUKRI_EMAIL", "")
    if not password:
        password = os.getenv("NAUKRI_PASSWORD", "")

    # 1. Build URL parts
    path_query = job_title.replace(" ", "-").lower() + "-jobs"
    if location:
        path_query += f"-in-{location.lower()}"
    k_param   = job_title.replace(" ", "+").lower()
    exp_query = f"experience={experience}"

    csv_file = os.path.join(root_dir, "jobs_database.csv")

    # FIX #4: Load existing links into a set so duplicate rows are never written
    existing_links: set[str] = set()
    if os.path.isfile(csv_file):
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) > 2:
                        existing_links.add(row[2])
        except (OSError, csv.Error) as e:
            logger.warning("Could not read existing CSV for dedup: %s", e)

    with open(csv_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Title", "Company", "Link", "Apply_Type", "Job_Description"])

        async with async_playwright() as p:
            user_data_dir = os.path.join(root_dir, "chrome_profile")
            context = await p.chromium.launch_persistent_context(
                user_data_dir, headless=False
            )
            page = context.pages[0]

            logger.info("--- Checking Login Status ---")
            await page.goto("https://www.naukri.com/", timeout=60000)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(3)

            if await page.locator("#login_Layer").count() > 0:
                if await page.locator("#login_Layer").is_visible():
                    logger.info("⚠️  NOT LOGGED IN")
                    if username and password:
                        logger.info("🤖 Auto-logging in with saved credentials...")
                        await page.goto(
                            "https://www.naukri.com/nlogin/login", timeout=30000
                        )
                        await page.wait_for_selector("#usernameField", timeout=15000)
                        await page.fill("#usernameField", username)
                        await asyncio.sleep(0.5)
                        await page.fill("#passwordField", password)
                        await asyncio.sleep(0.5)
                        await page.click("button[type='submit']")
                        logger.info("Waiting for login to complete...")
                        try:
                            await page.wait_for_selector(
                                ".nI-gNb-drawer__icon", timeout=20000
                            )
                            logger.info("✅ Login successful!")
                        # FIX #3: Specific exception instead of bare except
                        except PWTimeout:
                            logger.warning(
                                "⚠️  Automated login timed out — CAPTCHA may be shown. "
                                "Please log in manually in the browser window."
                            )
                            await page.wait_for_selector(
                                "#login_Layer", state="hidden", timeout=0
                            )
                    else:
                        logger.info(
                            "Please log in manually in the opened browser window. "
                            "The bot will wait here..."
                        )
                        await page.wait_for_selector(
                            "#login_Layer", state="hidden", timeout=0
                        )

                    logger.info("✅ Session saved.")
                    await asyncio.sleep(3)
            else:
                logger.info("✅ Already logged in!")

            jobs_collected = 0
            page_num = 1
            MAX_PAGES = 5

            while jobs_collected < max_jobs and page_num <= MAX_PAGES:
                try:
                    if page_num == 1:
                        current_url = (
                            f"https://www.naukri.com/{path_query}"
                            f"?k={k_param}&{exp_query}"
                        )
                    else:
                        current_url = (
                            f"https://www.naukri.com/{path_query}-{page_num}"
                            f"?k={k_param}&{exp_query}"
                        )

                    logger.info("--- Loading Page %d ---", page_num)
                    await page.goto(current_url)

                    # FIX #3: Specific exception
                    try:
                        await page.wait_for_selector("a.title", timeout=15000)
                    except PWTimeout:
                        logger.warning("Page %d timed out waiting for job titles. Stopping.", page_num)
                        break

                    # FIX #6: Single card selector — title & company from same element
                    job_cards = await page.query_selector_all("div.srp-jobtuple-wrapper")
                    if not job_cards:
                        logger.info("No more jobs found. Ending search.")
                        break

                    logger.info("Found %d cards on page %d.", len(job_cards), page_num)

                    for card in job_cards:
                        if jobs_collected >= max_jobs:
                            break

                        title_el   = await card.query_selector("a.title")
                        company_el = await card.query_selector("a.comp-name")
                        if not title_el or not company_el:
                            continue

                        title   = await title_el.inner_text()
                        company = await company_el.inner_text()
                        link    = await title_el.get_attribute("href")

                        # Strict title filter
                        search_words = job_title.lower().split()
                        if not all(
                            w in title.lower() for w in search_words if len(w) > 1
                        ):
                            logger.info("   -> Skipping irrelevant: %s at %s", title, company)
                            continue

                        if not link:
                            continue

                        # FIX #4: Skip if already in database
                        if link in existing_links:
                            logger.info("   -> Already in DB, skipping: %s", title)
                            continue

                        logger.info(
                            "[%d/%d] Opening: %s at %s",
                            jobs_collected + 1, max_jobs, title, company,
                        )

                        # FIX #5: Human-like random delay (already present, kept)
                        sleep_time = random.uniform(4.5, 8.5)
                        logger.info("   -> Pausing %.1fs (anti-bot)", sleep_time)
                        await asyncio.sleep(sleep_time)

                        job_page = await context.new_page()
                        try:
                            await job_page.goto(link, timeout=20000)
                            await job_page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(4)  # React hydration wait

                            # Apply-type detection via raw HTML scan
                            apply_type = "Naukri Apply"
                            raw_html = (await job_page.content()).lower()
                            if (
                                "apply on company site" in raw_html
                                or "apply on employer site" in raw_html
                                or "company-site-button" in raw_html
                                or "apply-company-site" in raw_html
                            ):
                                apply_type = "Company Website"

                            logger.info("   -> Apply type: %s", apply_type)

                            # FIX #7: Target JD container first; fall back to body
                            jd_el = await job_page.query_selector("div.job-desc")
                            if not jd_el:
                                jd_el = await job_page.query_selector("body")

                            job_text   = await jd_el.inner_text() if jd_el else ""
                            clean_text = clean_job_description(job_text).replace("\n", " ")

                            writer.writerow(
                                [title, company, link, apply_type, clean_text]
                            )
                            existing_links.add(link)  # update dedup set
                            logger.info("   -> Saved ✅")
                            jobs_collected += 1

                        # FIX #3: Specific exception for page-load failures
                        except (PWTimeout, OSError) as page_e:
                            logger.warning("   -> Failed to load page: %s", page_e)
                        except Exception as page_e:
                            logger.warning("   -> Unexpected error on job page: %s", page_e)
                        finally:
                            await job_page.close()

                    # Page-turn delay
                    page_sleep = random.uniform(3.0, 6.0)
                    logger.info("   -> Pausing %.1fs before next page", page_sleep)
                    await asyncio.sleep(page_sleep)
                    page_num += 1

                except Exception as e:
                    logger.error("Error on page %d: %s", page_num, e)
                    break

            logger.info("Closing browser...")
            await context.close()

    logger.info("Done! Jobs saved to: %s", csv_file)


if __name__ == "__main__":
    _title = sys.argv[1] if len(sys.argv) > 1 else "Product Manager"
    _exp   = sys.argv[2] if len(sys.argv) > 2 else "4"
    _limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    # FIX #2: Credentials are read from .env inside the function — not passed here
    asyncio.run(
        scrape_naukri(_title, "", experience=_exp, max_jobs=_limit)
    )
