import asyncio
import csv
import os
import random
import sys
from playwright.async_api import async_playwright

# Force UTF-8 encoding for Windows terminals to support emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def clean_job_description(text):
    if not text:
        return ""
    
    # 1. Try to find the start of the job description
    start_markers = ["Job description", "job description", "Job Description", "Job Highlights", "job highlights", "Job highlights"]
    start_idx = -1
    for marker in start_markers:
        idx = text.find(marker)
        if idx != -1:
            start_idx = idx
            break
            
    if start_idx != -1:
        text_desc = text[start_idx:]
    else:
        text_desc = text
        
    # 2. Try to find the end of the job description (to cut off footer noise)
    end_markers = [
        "Disclaimer:", 
        "Role:", 
        "Industry Type:", 
        "Similar jobs", 
        "About company", 
        "About the company", 
        "Reviews View all", 
        "Salary insights", 
        "Benefits & Perks", 
        "Services you might be interested in", 
        "Beware of imposters",
        "HomeJobs in"
    ]
    
    end_idx = len(text_desc)
    text_desc_lower = text_desc.lower()
    for marker in end_markers:
        idx = text_desc_lower.find(marker.lower())
        if idx != -1 and idx < end_idx:
            # Make sure it's not a tiny match early on
            if idx > 100:
                end_idx = idx
                
    return text_desc[:end_idx].strip()

async def scrape_naukri(job_title, location="", experience="0", max_jobs=100, username="", password=""):
    # 1. Build the SEO path
    path_query = job_title.replace(" ", "-").lower() + "-jobs"
    if location:
        path_query += f"-in-{location.lower()}"
        
    # 2. Build the Live Search keyword parameter
    k_param = job_title.replace(" ", "+").lower()
    
    # 3. Use the exact experience parameter
    exp_query = f"experience={experience}"
    
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    csv_file = os.path.join(root_dir, "jobs_database.csv")
    file_exists = os.path.isfile(csv_file)
    
    with open(csv_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['Title', 'Company', 'Link', 'Apply_Type', 'Job_Description'])

        async with async_playwright() as p:
            # Use a persistent Chrome profile so it remembers your Naukri Login!
            user_data_dir = os.path.join(root_dir, "chrome_profile")
            context = await p.chromium.launch_persistent_context(user_data_dir, headless=False)
            page = context.pages[0]
            
            print("\n--- Checking Login Status ---")
            await page.goto("https://www.naukri.com/", timeout=60000)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(3) # Give it time to load the navbar
            
            # Check if the "Login" button exists on the home page
            if await page.locator("#login_Layer").count() > 0:
                if await page.locator("#login_Layer").is_visible():
                    print("\n⚠️ YOU ARE NOT LOGGED IN!")
                    if username and password:
                        print("🤖 Automatically logging in using provided credentials...")
                        await page.goto("https://www.naukri.com/nlogin/login", timeout=30000)
                        await page.wait_for_selector("#usernameField", timeout=15000)
                        
                        # Simulate human typing
                        await page.fill("#usernameField", username)
                        await asyncio.sleep(0.5)
                        await page.fill("#passwordField", password)
                        await asyncio.sleep(0.5)
                        
                        await page.click("button[type='submit']")
                        
                        print("Waiting for login to complete...")
                        try:
                            # Wait until we see the user profile icon or it navigates away from login
                            await page.wait_for_selector(".nI-gNb-drawer__icon", timeout=20000)
                            print("✅ Login successful via automated credentials!")
                        except Exception as login_e:
                            print("⚠️ Automated login failed or required Captcha!")
                            print("Please use the opened browser window to log in manually.")
                            await page.wait_for_selector("#login_Layer", state="hidden", timeout=0)
                    else:
                        print("Please use the opened browser window to log into your Naukri account.")
                        print("The bot has paused and will wait patiently here until you log in...")
                        await page.wait_for_selector("#login_Layer", state="hidden", timeout=0)
                    
                    print("✅ Login successful! Session saved permanently.")
                    await asyncio.sleep(3)
            else:
                print("✅ Already logged in!")
                
            jobs_collected = 0
            page_num = 1
            
            # PAGINATION LOOP (Safety fail-safe to prevent infinite scrolling)
            MAX_PAGES_TO_SCAN = 5
            while jobs_collected < max_jobs and page_num <= MAX_PAGES_TO_SCAN:
                try:
                    if page_num == 1:
                        current_url = f"https://www.naukri.com/{path_query}?k={k_param}&{exp_query}"
                    else:
                        current_url = f"https://www.naukri.com/{path_query}-{page_num}?k={k_param}&{exp_query}"
                        
                    print(f"\n--- Loading Page {page_num} ({current_url}) ---")
                    await page.goto(current_url)
                    await page.wait_for_selector("a.title", timeout=15000)
                    
                    # GRAB THE WHOLE JOB CARD FIRST! (Fixes the misalignment bug)
                    job_cards = await page.query_selector_all("div.srp-jobtuple-wrapper")
                    
                    if len(job_cards) == 0:
                        print("No more jobs found! Ending search.")
                        break
                        
                    print(f"Found {len(job_cards)} jobs on this page.")
                    
                    for card in job_cards:
                        if jobs_collected >= max_jobs:
                            break
                            
                        # Extract data from inside this specific card so it never misaligns!
                        title_element = await card.query_selector("a.title")
                        company_element = await card.query_selector("a.comp-name")
                        
                        if not title_element or not company_element:
                            continue
                            
                        title = await title_element.inner_text()
                        company = await company_element.inner_text()
                        link = await title_element.get_attribute("href")
                        
                        # STRICT FILTER
                        search_words = job_title.lower().split()
                        title_lower = title.lower()
                        
                        # Fix: Changed 'any' to 'all' so it strictly requires ALL keywords 
                        # Example: "Associate Product Manager" requires Associate AND Product AND Manager
                        if not all(word in title_lower for word in search_words if len(word) > 1):
                            print(f"   -> Skipping irrelevant job: {title} at {company}")
                            continue
                        
                        if not link:
                            continue
                            
                        print(f"[{jobs_collected+1}/{max_jobs}] Opening Tab for: {title} at {company}")
                        
                        # RANDOMIZED BREATHING 1: Wait randomly between 4.5 to 8.5 seconds before clicking a job
                        sleep_time = random.uniform(4.5, 8.5)
                        print(f"   -> 🤫 Shh... acting like a human (pausing {sleep_time:.1f}s)")
                        await asyncio.sleep(sleep_time)
                        
                        job_page = await context.new_page()
                        try:
                            await job_page.goto(link, timeout=20000)
                            await job_page.wait_for_load_state("domcontentloaded")
                            
                            # CRITICAL FIX: Naukri is a React app. 
                            # 'domcontentloaded' fires before the API returns the job data!
                            # We MUST wait a few seconds for the page to actually render the buttons and description.
                            await asyncio.sleep(4)
                            
                            # Explicit Apply Type Detection (Senior SWE Fix: Raw HTML inspection)
                            apply_type = "Naukri Apply" 
                            
                            # Grab the entire raw HTML of the page to bypass all CSS/Locator issues
                            raw_html = await job_page.content()
                            raw_html_lower = raw_html.lower()
                            
                            if "apply on company site" in raw_html_lower or "apply on employer site" in raw_html_lower:
                                apply_type = "Company Website"
                            elif "company-site-button" in raw_html_lower or "apply-company-site" in raw_html_lower:
                                apply_type = "Company Website"
                                
                            print(f"   -> Detected Apply Type: {apply_type}")
                            
                            body_element = await job_page.query_selector("body")
                            job_text = await body_element.inner_text()
                            clean_text = clean_job_description(job_text).replace('\n', ' ')
                            
                            writer.writerow([title, company, link, apply_type, clean_text])
                            print(f"   -> Successfully saved to database!\n")
                            jobs_collected += 1
                            
                        except Exception as page_e:
                            print(f"   -> Failed to load description: {page_e}\n")
                        finally:
                            await job_page.close()
                            
                    # RANDOMIZED BREATHING 2: Wait longer (3 to 6 seconds) before clicking "Next Page"
                    page_sleep = random.uniform(3.0, 6.0)
                    print(f"   -> 🤫 Reading the page like a human (pausing {page_sleep:.1f}s before flipping page)")
                    await asyncio.sleep(page_sleep)
                    
                    page_num += 1
                    
                except Exception as e:
                    print(f"Error on page {page_num}: {e}")
                    break
                    
            print("Closing browser...")
            await context.close()
    
    print(f"Done! Check the new file: {csv_file}")

if __name__ == "__main__":
    import sys
    target_title = "Product Manager"
    target_exp = "4"
    uname = ""
    pwd = ""
    
    if len(sys.argv) > 2:
        target_title = sys.argv[1]
        target_exp = sys.argv[2]
    
    limit = 5
    if len(sys.argv) > 4:
        uname = sys.argv[3]
        pwd = sys.argv[4]
    
    if len(sys.argv) > 5:
        limit = int(sys.argv[5])
    asyncio.run(scrape_naukri(target_title, "", experience=target_exp, max_jobs=limit, username=uname, password=pwd))