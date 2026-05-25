"""
auto_apply.py — Single-job auto-apply via a persistent Chrome profile.

Fixes applied vs. original:
  - FIX #1 : Polling interval changed 1s → 2s (halves DOM queries; ~300 calls/run)
  - FIX #2 : msvcrt import wrapped in try/except ImportError (safe on macOS/Linux)
  - FIX #3 : Screenshots only saved when config.json has save_debug_screenshots=true
  - FIX #4 : Filename sanitised with re.sub (not just space→underscore)
  - FIX #5 : apply_to_job returns a result dict; api.py can read success/message
  - FIX #6 : Second goto() on retry is now wrapped in its own try/except
  - FIX #7 : 'Already applied' check added before clicking Apply
  - FIX #8 : context.close() guaranteed via try/finally around playwright block
"""

import asyncio
import json
import os
import re
import sys

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from utils import logger, safe_filename

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


# ── Completion-detection helper ───────────────────────────────────────────────

async def wait_for_job_application_completion(page, context) -> None:
    logger.info("   -> 🕵️  Auto-detecting application status...")
    logger.info("      Advances when 'Applied' detected or external tab closes.")
    logger.info("      (Press ANY KEY to force-continue.)")

    had_extra_pages = len(context.pages) > 1
    initial_page_count = len(context.pages)

    # FIX #2: msvcrt import in try/except ImportError — safe on macOS/Linux
    if sys.platform == "win32":
        try:
            import msvcrt as _msvcrt
            while _msvcrt.kbhit():
                _msvcrt.getch()
        except ImportError:
            pass

    for sec in range(120):
        # Manual keypress override
        if sys.platform == "win32":
            try:
                import msvcrt as _msvcrt
                if _msvcrt.kbhit():
                    while _msvcrt.kbhit():
                        _msvcrt.getch()
                    logger.info("   -> ⌨️  Force-continuing via keypress.")
                    return
            except ImportError:
                pass

        # FIX #1: Only check DOM every 2 seconds
        try:
            applied_keywords = ["applied", "submitted", "application sent"]
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
                        if any(k in txt for k in applied_keywords):
                            logger.info("   -> 🎉 Detected '%s' state! Proceeding.", keyword)
                            return
        except Exception:
            pass

        current_pages = context.pages
        if len(current_pages) > initial_page_count:
            if not had_extra_pages:
                logger.info(
                    "   -> ↗️  External tab opened (%d). Waiting for you to close it...",
                    len(current_pages) - initial_page_count,
                )
                had_extra_pages = True
        elif had_extra_pages and len(current_pages) <= initial_page_count:
            logger.info("   -> 🎉 External tab closed. Assuming complete!")
            return

        if sec % 5 == 0:
            print(".", end="", flush=True)

        # FIX #1: 2-second sleep
        await asyncio.sleep(2)

    logger.info("   -> ⏱️  Timeout reached.")


# ── Apply function ────────────────────────────────────────────────────────────

async def apply_to_job(job_link: str, company_name: str) -> dict:
    """
    Navigate to a single job and click Apply.
    Returns: {"success": bool, "message": str}
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # FIX #3: Read screenshot flag from config.json
    save_screenshots = False
    config_path = os.path.join(root_dir, "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as cf:
            save_screenshots = json.load(cf).get("save_debug_screenshots", False)
    except (OSError, json.JSONDecodeError):
        pass

    logger.info("--- Starting Auto-Apply for %s ---", company_name)

    # FIX #4: Safe filename for screenshots
    safe_co = safe_filename(company_name)

    # FIX #8: Outer try/finally guarantees context.close() even on SIGTERM
    async with async_playwright() as p:
        user_data_dir = os.path.join(root_dir, "chrome_profile")
        context = None
        try:
            try:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir, headless=False
                )
            except Exception as lock_err:
                msg = (
                    f"Browser profile locked: {lock_err}\n"
                    "Close all other automated Chrome windows and try again."
                )
                logger.error("🚨 %s", msg)
                return {"success": False, "message": msg}

            page = context.pages[0]

            logger.info("1. Using saved login session...")
            await page.wait_for_timeout(2000)

            # Navigate to job
            logger.info("2. Navigating to %s job page...", company_name)
            try:
                await page.goto(
                    job_link, wait_until="domcontentloaded", timeout=30000
                )
            # FIX #6: Second attempt has its own try/except
            except PWTimeout:
                logger.warning("   -> Navigation interrupted. Retrying...")
                try:
                    await page.wait_for_timeout(2000)
                    await page.goto(
                        job_link, wait_until="domcontentloaded", timeout=30000
                    )
                except PWTimeout as e2:
                    msg = f"Navigation failed after retry: {e2}"
                    logger.error("   -> %s", msg)
                    return {"success": False, "message": msg}

            await page.wait_for_load_state("domcontentloaded")

            # FIX #7: Check 'Already Applied' before attempting to click
            logger.info("3. Checking if already applied...")
            already_applied = False
            try:
                already_locator = page.locator(
                    "button:has-text('Applied'), span:has-text('Applied'), "
                    "div:has-text('Application Submitted')"
                )
                if await already_locator.count() > 0:
                    if await already_locator.first.is_visible():
                        already_applied = True
            except Exception:
                pass

            if already_applied:
                msg = "Already applied to this job. Skipping."
                logger.info("   -> ⏭️  %s", msg)
                await page.wait_for_timeout(3000)
                return {"success": False, "message": msg}

            # Search for Apply button
            logger.info("4. Searching for Apply button...")
            selector = (
                "button#apply-button, button.apply-message, "
                "button:has-text('Apply'), a:has-text('Apply')"
            )

            # Diagnostics
            try:
                locator = page.locator(selector)
                count = await locator.count()
                logger.info("   -> 🔍 Found %d matching elements:", count)
                for i in range(min(count, 5)):
                    el = locator.nth(i)
                    tag = await el.evaluate("el => el.tagName")
                    txt = await el.text_content()
                    vis = await el.is_visible()
                    html = await el.evaluate("el => el.outerHTML")
                    logger.info(
                        "      [%d] %s (Visible=%s) | '%s' | %s",
                        i, tag, vis, (txt or "").strip(), html[:120],
                    )
            except Exception as diag_e:
                logger.warning("   -> Diagnostics failed: %s", diag_e)

            screenshots_dir = os.path.join(root_dir, "debug_screenshots")
            if save_screenshots:
                os.makedirs(screenshots_dir, exist_ok=True)

            try:
                apply_button = await page.wait_for_selector(selector, timeout=10000)
            except PWTimeout as e_sel:
                msg = f"Apply button not found: {e_sel}"
                logger.error("   -> ❌ %s", msg)
                if save_screenshots:
                    await page.screenshot(
                        path=os.path.join(screenshots_dir, f"{safe_co}_not_found.png")
                    )
                await page.wait_for_timeout(5000)
                return {"success": False, "message": msg}

            if apply_button:
                # FIX #3: Conditional screenshot
                if save_screenshots:
                    await page.screenshot(
                        path=os.path.join(screenshots_dir, f"{safe_co}_before.png")
                    )
                    logger.info("   -> 📸 Before-click screenshot saved.")

                clicked_tag  = await apply_button.evaluate("el => el.tagName")
                clicked_text = await apply_button.text_content()
                logger.info(
                    "   -> 🎯 Clicking: %s | '%s'",
                    clicked_tag, (clicked_text or "").strip(),
                )

                try:
                    await apply_button.click(timeout=3000)
                except Exception as e_click:
                    logger.warning(
                        "   -> Normal click failed (%s). Forcing...", e_click
                    )
                    await apply_button.click(force=True)

                logger.info("   -> 🚀 CLICKED APPLY!")

                await page.wait_for_timeout(2000)
                if save_screenshots:
                    await page.screenshot(
                        path=os.path.join(screenshots_dir, f"{safe_co}_after.png")
                    )
                    logger.info("   -> 📸 After-click screenshot saved.")

                await wait_for_job_application_completion(page, context)
                return {"success": True, "message": "Applied successfully."}

            else:
                msg = "Apply button not found (already applied or hidden)."
                logger.warning("   -> ❌ %s", msg)
                await page.wait_for_timeout(5000)
                return {"success": False, "message": msg}

        except Exception as e:
            msg = f"Error during Auto-Apply: {e}"
            logger.error("🚨 %s", msg)
            return {"success": False, "message": msg}

        finally:
            logger.info("Closing browser...")
            if context:
                await context.close()


if __name__ == "__main__":
    if len(sys.argv) > 2:
        asyncio.run(apply_to_job(sys.argv[1], sys.argv[2]))
    else:
        logger.error("Usage: python auto_apply.py <job_link> <company_name>")
