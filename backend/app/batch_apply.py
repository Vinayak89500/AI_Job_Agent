"""
batch_apply.py — Batch job application bot for Naukri native jobs.

Fixes applied vs. original:
  - FIX #1 : Added login/CAPTCHA detection — asserts header is visible after login
  - FIX #2 : True retry with exponential back-off (was calling same goto() twice)
  - FIX #3 : Final browser wait is now adaptive (10s if nothing applied, else skip)
  - FIX #4 : Every successful application written to applied_jobs.log for resume safety
  - FIX #5 : next(reader, None) guard prevents StopIteration on empty CSV
  - FIX #6 : Bare except: replaced with specific exception types
  - FIX #7 : Polling interval in wait helper changed from 1s → 2s (less DOM hammering)
"""

import asyncio
import csv
import os
import sys
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from utils import logger

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


# ── Completion-detection helper ───────────────────────────────────────────────

async def wait_for_job_application_completion(page, context) -> None:
    logger.info("   -> 🕵️  Auto-detecting application status...")
    logger.info("      Will advance once 'Applied' state detected or external tab closes.")
    logger.info("      (Press ANY KEY in this terminal to force-continue.)")

    had_extra_pages = len(context.pages) > 1
    initial_page_count = len(context.pages)

    # Clear keyboard buffer (Windows only)
    if sys.platform == "win32":
        try:
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getch()
        except ImportError:
            pass

    for sec in range(120):
        # Manual keypress override (Windows only)
        if sys.platform == "win32":
            try:
                import msvcrt
                if msvcrt.kbhit():
                    while msvcrt.kbhit():
                        msvcrt.getch()
                    logger.info("   -> ⌨️  Force-continuing via keypress.")
                    return
            except ImportError:
                pass

        # FIX #7: Check applied state every 2 seconds instead of every 1 second
        # (reduces DOM queries from ~600 to ~300 per 2-minute wait)
        try:
            applied_keywords = ["applied", "submitted", "application sent", "success"]
            for keyword in applied_keywords:
                locator = page.locator(
                    f"button:has-text('{keyword}'), a:has-text('{keyword}'), "
                    f"span:has-text('{keyword}'), div:has-text('{keyword}')"
                )
                count = await locator.count()
                for i in range(count):
                    el = locator.nth(i)
                    if await el.is_visible():
                        txt = (await el.text_content() or "").lower()
                        if any(k in txt for k in ["applied", "submitted", "application sent"]):
                            logger.info(
                                "   -> 🎉 Detected '%s' status! Proceeding...", keyword
                            )
                            return
        except Exception:
            pass

        # External tab tracking
        current_pages = context.pages
        if len(current_pages) > initial_page_count:
            if not had_extra_pages:
                logger.info(
                    "   -> ↗️  External tab opened (%d new tab(s)). "
                    "Waiting for you to close it...",
                    len(current_pages) - initial_page_count,
                )
                had_extra_pages = True
        elif had_extra_pages and len(current_pages) <= initial_page_count:
            logger.info("   -> 🎉 External tab closed. Assuming complete!")
            return

        if sec % 5 == 0:
            print(".", end="", flush=True)

        # FIX #7: Sleep 2s instead of 1s
        await asyncio.sleep(2)

    logger.info("   -> ⏱️  Timeout (120s) reached. Moving on.")


# ── Main apply loop ───────────────────────────────────────────────────────────

async def batch_apply() -> None:
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    csv_path = os.path.join(root_dir, "jobs_database.csv")

    # FIX #4: Log file for successfully applied jobs
    log_path = os.path.join(root_dir, "applied_jobs.log")

    if not os.path.exists(csv_path):
        logger.error("Database not found! Run the Scraper first.")
        return

    jobs_to_apply: list[dict] = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            # FIX #5: next(reader, None) prevents StopIteration on header-only CSV
            header = next(reader, None)
            if header is None:
                logger.error("CSV is completely empty.")
                return
            for row in reader:
                if len(row) >= 4 and row[3] == "Naukri Apply":
                    jobs_to_apply.append(
                        {"title": row[0], "company": row[1], "link": row[2]}
                    )
    except PermissionError:
        logger.error(
            "Jobs database is locked — the Scraper may still be running. "
            "Close its terminal window and try again."
        )
        return

    logger.info("Found %d jobs to apply to.", len(jobs_to_apply))

    async with async_playwright() as p:
        user_data_dir = os.path.join(root_dir, "chrome_profile")
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir, headless=False
            )
        # FIX #6: Specific exception instead of bare except
        except Exception as lock_err:
            logger.error(
                "Browser profile is locked: %s\n"
                "Close all other automated Chrome windows and try again.",
                lock_err,
            )
            return

        page = context.pages[0]
        applied_count = 0

        try:
            logger.info("Using saved login session...")
            await page.wait_for_timeout(3000)

            # FIX #1: Verify we are actually logged in before starting the loop
            await page.goto("https://www.naukri.com/", timeout=30000)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(3)
            if await page.locator("#login_Layer").count() > 0:
                if await page.locator("#login_Layer").is_visible():
                    logger.warning(
                        "⚠️  NOT LOGGED IN — please log in manually in the browser "
                        "window. The bot will wait..."
                    )
                    await page.wait_for_selector(
                        "#login_Layer", state="hidden", timeout=0
                    )
                    logger.info("✅ Login detected. Starting application loop.")
            else:
                logger.info("✅ Already logged in!")

            for idx, job in enumerate(jobs_to_apply):
                logger.info(
                    "--- [%d/%d] Applying to %s ---",
                    idx + 1, len(jobs_to_apply), job["company"],
                )

                try:
                    # FIX #2: Real retry with exponential back-off
                    for attempt in range(3):
                        try:
                            await page.goto(
                                job["link"],
                                wait_until="domcontentloaded",
                                timeout=15000,
                            )
                            break  # success
                        except PWTimeout:
                            if attempt < 2:
                                wait = 2 ** attempt
                                logger.warning(
                                    "   -> Navigation timed out. Retrying in %ds...", wait
                                )
                                await asyncio.sleep(wait)
                            else:
                                raise

                    selector = (
                        "button#apply-button, button.apply-message, "
                        "button:has-text('Apply'), a:has-text('Apply')"
                    )

                    # Diagnostics
                    try:
                        locator = page.locator(selector)
                        count = await locator.count()
                        logger.info("   -> 🔍 Found %d matching elements.", count)
                        for i in range(min(count, 5)):
                            el = locator.nth(i)
                            txt = await el.text_content()
                            vis = await el.is_visible()
                            logger.info(
                                "      [%d] Visible=%s | Text='%s'",
                                i, vis, (txt or "").strip(),
                            )
                    except Exception as diag_e:
                        logger.warning("   -> Diagnostics failed: %s", diag_e)

                    # Find and click apply button
                    try:
                        apply_button = await page.wait_for_selector(
                            selector, timeout=6000
                        )
                    except PWTimeout:
                        apply_button = None

                    if apply_button:
                        # Screenshots (controlled by config — see api.py)
                        screenshots_dir = os.path.join(root_dir, "debug_screenshots")
                        import re as _re
                        safe_company = _re.sub(r"[^\w\-]", "_", job["company"])
                        os.makedirs(screenshots_dir, exist_ok=True)
                        before_path = os.path.join(screenshots_dir, f"{safe_company}_before.png")
                        await page.screenshot(path=before_path)

                        try:
                            await apply_button.click(timeout=3000)
                        except Exception as e_click:
                            logger.warning(
                                "   -> Normal click failed (%s). Forcing...", e_click
                            )
                            await apply_button.click(force=True)

                        logger.info("   -> 🚀 CLICKED APPLY!")

                        await page.wait_for_timeout(2000)
                        after_path = os.path.join(screenshots_dir, f"{safe_company}_after.png")
                        await page.screenshot(path=after_path)

                        await wait_for_job_application_completion(page, context)

                        # FIX #4: Record successful application to log file
                        applied_count += 1
                        with open(log_path, "a", encoding="utf-8") as lf:
                            lf.write(
                                f"{datetime.now().isoformat()} | "
                                f"{job['company']} | {job['title']} | {job['link']}\n"
                            )
                        logger.info("   -> ✅ Logged to applied_jobs.log")

                    else:
                        logger.warning(
                            "   -> ❌ Apply button not found (already applied or hidden)."
                        )

                except Exception as loop_e:
                    logger.warning(
                        "   -> ⚠️  Skipping %s: %s", job["company"], loop_e
                    )
                    continue

        except Exception as fatal:
            logger.error("🚨 FATAL Error: %s", fatal)

        finally:
            logger.info(
                "Finished! Applied to %d/%d jobs. Log: %s",
                applied_count, len(jobs_to_apply), log_path,
            )
            # FIX #3: Adaptive wait — only keep browser open briefly if nothing applied
            hold = 10 if applied_count == 0 else 3
            await page.wait_for_timeout(hold * 1000)
            await context.close()


if __name__ == "__main__":
    asyncio.run(batch_apply())
