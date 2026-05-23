import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import csv
import asyncio
from playwright.async_api import async_playwright

async def wait_for_job_application_completion(page, context):
    print("\n   -> 🕵️ Auto-detecting application status...")
    print("      Script will auto-advance once the button changes to 'Applied' or the external tab is closed.")
    print("      (You can also press ANY KEY in this terminal to force-continue to the next job.)")
    
    had_extra_pages = len(context.pages) > 1
    initial_page_count = len(context.pages)
    
    # Clean keyboard buffer first if msvcrt is available on Windows
    if sys.platform == "win32":
        try:
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getch()
        except Exception:
            pass

    for sec in range(120): # Max wait 120 seconds (2 minutes)
        # 1. Check for manual keypress (Windows-only non-blocking)
        if sys.platform == "win32":
            try:
                import msvcrt
                if msvcrt.kbhit():
                    # Clear buffer
                    while msvcrt.kbhit():
                        msvcrt.getch()
                    print("\n   -> ⌨️ Force-continuing to the next job via manual keypress!")
                    return
            except Exception:
                pass
            
        # 2. Check if the apply button or any prominent button/span indicates "Applied"
        try:
            applied_keywords = ["applied", "submitted", "application sent", "success"]
            for keyword in applied_keywords:
                locator = page.locator(f"button:has-text('{keyword}'), a:has-text('{keyword}'), span:has-text('{keyword}'), div:has-text('{keyword}'), p:has-text('{keyword}')")
                count = await locator.count()
                for i in range(count):
                    el = locator.nth(i)
                    if await el.is_visible():
                        txt = (await el.text_content() or "").lower()
                        if "applied" in txt or "submitted" in txt or "application sent" in txt:
                            print(f"\n   -> 🎉 Auto-detected '{keyword.capitalize()}' status on page! Proceeding...")
                            return
        except Exception:
            pass
            
        # 3. Check external tabs
        current_pages = context.pages
        if len(current_pages) > initial_page_count:
            if not had_extra_pages:
                print(f"\n   -> ↗️ External application tab detected ({len(current_pages) - initial_page_count} new tab(s)). Waiting for you to finish and close the tab(s)...")
                had_extra_pages = True
        elif had_extra_pages and len(current_pages) <= initial_page_count:
            print("\n   -> 🎉 External application tab was closed. Assuming completed!")
            return
            
        # Just print a small dot every 5 seconds to show we are alive
        if sec % 5 == 0:
            print(".", end="", flush=True)
            
        await asyncio.sleep(1)
        
    print("\n   -> ⏱️ Timeout (120s) reached. Moving to the next job.")

async def batch_apply():
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    
    email = ""
    password = ""
    csv_path = os.path.join(root_dir, "jobs_database.csv")
    
    # Read jobs
    jobs_to_apply = []
    if not os.path.exists(csv_path):
        print("Database is empty! Run the Scraper first.")
        return

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader) 
            for row in reader:
                if len(row) >= 4 and row[3] == "Naukri Apply":
                    jobs_to_apply.append({"title": row[0], "company": row[1], "link": row[2]})
    except PermissionError:
        print("\n🚨 CRITICAL ERROR: The Jobs Database is currently locked!")
        print("This usually means the Scraper is actively running and writing jobs to the file.")
        print("Please wait for the Scraper to finish or close its terminal window before Batch Applying.\n")
        return
                
    print(f"Found {len(jobs_to_apply)} jobs to batch apply!")
    
    async with async_playwright() as p:
        # Use the EXACT SAME persistent profile from the scraper!
        user_data_dir = os.path.join(root_dir, "chrome_profile")
        try:
            context = await p.chromium.launch_persistent_context(user_data_dir, headless=False)
        except Exception as lock_err:
            print("\n🚨 CRITICAL ERROR: Browser Profile is Locked!")
            print("You probably have the Scraper or another Auto-Apply window open.")
            print("Please close all black terminal windows and automated Chrome browsers and try again.\n")
            return
            
        page = context.pages[0]
        
        try:
            print("Using saved login session...")
            # We skip the fragile automated login block completely!
            await page.wait_for_timeout(3000)
            
            for idx, job in enumerate(jobs_to_apply):
                print(f"\n--- [{idx+1}/{len(jobs_to_apply)}] Applying to {job['company']} ---")
                
                # BULLETPROOF BLOCK: If anything fails here, it skips to the next job!
                try:
                    try:
                        # Shorter timeout. If it takes longer than 15s to load, skip it!
                        await page.goto(job['link'], wait_until="domcontentloaded", timeout=15000)
                    except:
                        print("   -> Retrying navigation...")
                        await page.goto(job['link'], wait_until="domcontentloaded", timeout=15000)
                    
                    # Diagnostics: list all elements matching the selector
                    selector = "button#apply-button, button.apply-message, button:has-text('Apply'), a:has-text('Apply')"
                    try:
                        locator = page.locator(selector)
                        count = await locator.count()
                        print(f"   -> 🔍 Found {count} matching elements for the selector:")
                        for i in range(count):
                            el = locator.nth(i)
                            tag = await el.evaluate("el => el.tagName")
                            text = await el.text_content()
                            is_vis = await el.is_visible()
                            outer_html = await el.evaluate("el => el.outerHTML")
                            trunc_html = outer_html[:150] + "..." if len(outer_html) > 150 else outer_html
                            print(f"      [{i}] {tag} (Visible: {is_vis}) | Text: '{text.strip()}' | HTML: {trunc_html}")
                    except Exception as diag_err:
                        print(f"   -> ⚠️ Failed to run selector diagnostics: {diag_err}")

                    # Ensure screenshots directory exists
                    screenshots_dir = os.path.join(root_dir, "debug_screenshots")
                    os.makedirs(screenshots_dir, exist_ok=True)
                    
                    try:
                        apply_button = await page.wait_for_selector(selector, timeout=6000)
                    except Exception as e_sel:
                        print(f"   -> ❌ Timeout waiting for selector: {e_sel}")
                        apply_button = None
                    
                    if apply_button:
                        # Take screenshot before click
                        before_path = os.path.join(screenshots_dir, f"{job['company'].replace(' ', '_')}_before.png")
                        await page.screenshot(path=before_path)
                        print(f"   -> 📸 Saved before-click screenshot to: {before_path}")
                        
                        # Inspect the specific element we are clicking
                        clicked_tag = await apply_button.evaluate("el => el.tagName")
                        clicked_text = await apply_button.text_content()
                        clicked_html = await apply_button.evaluate("el => el.outerHTML")
                        print(f"   -> 🎯 Click Target: {clicked_tag} | Text: '{clicked_text.strip()}' | HTML: {clicked_html}")
                        
                        try:
                            # Try clicking normally first
                            print("   -> Attempting normal click...")
                            await apply_button.click(timeout=3000)
                        except Exception as e_click:
                            print(f"   -> ⚠️ Normal click failed/intercepted: {e_click}. Trying with force=True...")
                            await apply_button.click(force=True)
                        
                        print("   -> 🚀 CLICKED APPLY!")
                        
                        # Wait for a brief moment for transition, then take after-click screenshot
                        await page.wait_for_timeout(2000)
                        after_path = os.path.join(screenshots_dir, f"{job['company'].replace(' ', '_')}_after.png")
                        await page.screenshot(path=after_path)
                        print(f"   -> 📸 Saved after-click screenshot to: {after_path}")
                        
                        await wait_for_job_application_completion(page, context)
                    else:
                        print("   -> ❌ Could not find Apply button. (Already applied or hidden).")
                        
                except Exception as loop_e:
                    print(f"   -> ⚠️ Skipping {job['company']} due to error: {loop_e}")
                    continue # This tells the bot to ignore the crash and move to the next job!
                
        except Exception as e:
            print(f"🚨 FATAL Error: {e}")
        finally:
            print("Finished Batch Apply Pipeline!")
            # Keep browser open at the very end so you can see the final state
            await page.wait_for_timeout(60000)
            await context.close()

if __name__ == "__main__":
    asyncio.run(batch_apply())