import os
import sys
import asyncio
from playwright.async_api import async_playwright

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

async def apply_to_job(job_link, company_name):
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        
    print(f"\n--- Starting Auto-Apply for {company_name} ---")
    
    async with async_playwright() as p:
        # Use the EXACT SAME persistent profile from the scraper!
        user_data_dir = os.path.join(root_dir, "chrome_profile")
        try:
            context = await p.chromium.launch_persistent_context(user_data_dir, headless=False)
        except Exception as lock_err:
            print("\n🚨 CRITICAL ERROR: Browser Profile is Locked!")
            print("You probably have the Scraper or another Auto-Apply window open.")
            print("Please close all black terminal windows and automated Chrome browsers and try again.\n")
            return False
            
        page = context.pages[0]
        
        try:
            print("1. Using saved login session...")
            await page.wait_for_timeout(2000)
            
            # 2. Navigate to the specific Job
            print(f"2. Navigating to {company_name} job page...")
            try:
                # wait_until="domcontentloaded" is faster and less prone to getting aborted by ads
                await page.goto(job_link, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print("   -> Navigation interrupted by Naukri popup. Retrying...")
                await page.wait_for_timeout(2000)
                # Second attempt usually succeeds
                await page.goto(job_link, wait_until="domcontentloaded", timeout=30000)
                
            await page.wait_for_load_state("domcontentloaded")
            
            # 3. Hit the Apply Button
            print("3. Searching for Apply button...")
            
            # Naukri uses a few different class names for their apply button
            apply_button = await page.wait_for_selector("button.apply-message, button#apply-button", timeout=10000)
            
            if apply_button:
                await apply_button.click()
                print("🚀 CLICKED APPLY!")
                
                # Wait 5 seconds to see if a questionnaire pops up
                await page.wait_for_timeout(5000)
                print("Job Applied! Check the browser to see if there are mandatory questions.")
            else:
                print("❌ Could not find the Apply button. (Might be an external site).")
                
            # Keep browser open for 10 seconds so you can see what happened before it closes
            await page.wait_for_timeout(10000)
            
        except Exception as e:
            print(f"🚨 Error during Auto-Apply: {e}")
        finally:
            print("Closing browser...")
            await context.close()

if __name__ == "__main__":
    import sys
    # If the dashboard sends a link, use it!
    if len(sys.argv) > 2:
        target_link = sys.argv[1]
        target_company = sys.argv[2]
        asyncio.run(apply_to_job(target_link, target_company))
    else:
        print("Please provide a job link and company name.")

