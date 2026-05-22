import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import csv
import asyncio
from playwright.async_api import async_playwright

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
                    
                    try:
                        # Searches for ALL possible buttons at the exact same time!
                        apply_button = await page.wait_for_selector(
                            "button#apply-button, button.apply-message, button:has-text('Apply'), a:has-text('Apply')", 
                            timeout=6000
                        )
                    except:
                        apply_button = None
                    
                    if apply_button:
                        await apply_button.click(force=True)
                        print("   -> 🚀 CLICKED APPLY!")
                        print("   -> ⏸️ Pausing for 5 seconds. If a questionnaire pops up, fill it now!")
                        await page.wait_for_timeout(5000) 
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