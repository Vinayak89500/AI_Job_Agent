import os
import re
import csv
import sys
import subprocess
import json
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI()

# Paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
CSV_PATH = os.path.join(ROOT_DIR, "jobs_database.csv")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
MASTER_PROFILE_PATH = os.path.join(ROOT_DIR, "Master_Career_Profile.txt")

# Models for the incoming UI Data
class ApplyRequest(BaseModel):
    link: str
    company: str

class ScrapeRequest(BaseModel):
    job_title: str
    experience: str
    max_jobs: int = 5
    username: str = ""
    password: str = ""

class OpenRequest(BaseModel):
    filename: str

class SetupRequest(BaseModel):
    fullName: str
    cityCountry: str
    phone: str
    email: str
    linkedin: str
    groqApiKey: str
    resumeText: str

# --- GET ENDPOINTS (Read Data) ---

@app.get("/")
def read_root():
    with open(os.path.join(FRONTEND_DIR, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/config")
def get_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Config not found"}

@app.post("/api/setup")
def setup_agent(req: SetupRequest):
    try:
        # 1. Save config.json
        config_data = {
            "fullName": req.fullName,
            "cityCountry": req.cityCountry,
            "phone": req.phone,
            "email": req.email,
            "linkedin": req.linkedin,
            "groqApiKey": req.groqApiKey
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
            
        # 2. Save Master_Career_Profile.txt
        with open(MASTER_PROFILE_PATH, "w", encoding="utf-8") as f:
            f.write(req.resumeText)
            
        # 3. Trigger db_loader.py to embed the resume!
        db_loader_path = os.path.join(ROOT_DIR, "backend", "app", "db_loader.py")
        env_vars = os.environ.copy()
        env_vars["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen(
            [sys.executable, db_loader_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            env=env_vars
        )
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/jobs")
def get_jobs():
    jobs = []
    output_dir = os.path.join(ROOT_DIR, "Tailored_Resumes")
    
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader, None)
            for row in reader:
                if len(row) >= 5:
                    company = row[1]
                    title = row[0]
                    apply_type = row[3]
                    
                    # Check if resume was generated
                    safe_company = re.sub(r'[\\/*?:"<>|]', "_", company).replace(" ", "_")
                    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title).replace(" ", "_")
                    filename = f"{safe_company}_{safe_title}.md"
                    filepath = os.path.join(output_dir, filename)
                    
                    resume_status = "Not Applicable" if apply_type == "Naukri Apply" else "Not Generated"
                    ats_score = None
                    
                    if apply_type == "Company Website" and os.path.exists(filepath):
                        resume_status = filename.replace('.md', '.docx')
                        # Parse ATS Score from the file
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                for line in f:
                                    if "**ATS Score:**" in line:
                                        ats_score = line.replace("**ATS Score:**", "").strip()
                                        break
                        except:
                            pass
                            
                    jobs.append({
                        "title": title,
                        "company": company,
                        "link": row[2],
                        "apply_type": apply_type,
                        "resume_file": resume_status,
                        "ats_score": ats_score
                    })
    return jobs

# --- POST ENDPOINTS (Trigger Actions) ---

@app.post("/api/reset")
def reset_session():
    import shutil
    
    # 1. Clear Jobs Database
    csv_file = os.path.join(ROOT_DIR, "jobs_database.csv")
    if os.path.exists(csv_file):
        with open(csv_file, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['Title', 'Company', 'Link', 'Apply_Type', 'Job_Description'])
            
    # 2. Clear Generated Resumes
    resumes_dir = os.path.join(ROOT_DIR, "Tailored_Resumes")
    if os.path.exists(resumes_dir):
        for f in os.listdir(resumes_dir):
            file_path = os.path.join(resumes_dir, f)
            if os.path.isfile(file_path):
                os.unlink(file_path)
                
    return {"status": "success"}

@app.post("/api/apply")
def trigger_auto_apply(req: ApplyRequest):
    script_path = os.path.join(ROOT_DIR, "backend", "app", "auto_apply.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    subprocess.Popen(
        [sys.executable, script_path, req.link, req.company],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env_vars
    )
    return {"status": "success"}

@app.post("/api/scrape")
def trigger_scrape(req: ScrapeRequest):
    script_path = os.path.join(ROOT_DIR, "backend", "app", "scraper.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    subprocess.Popen(
        [sys.executable, script_path, req.job_title, req.experience, req.username, req.password, str(req.max_jobs)], 
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env_vars
    )
    return {"status": "success"}

@app.post("/api/batch_apply")
def trigger_batch_apply():
    script_path = os.path.join(ROOT_DIR, "backend", "app", "batch_apply.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    subprocess.Popen(
        [sys.executable, script_path], 
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env_vars
    )
    return {"status": "success"}

@app.post("/api/generate")
def trigger_generate():
    script_path = os.path.join(ROOT_DIR, "backend", "app", "main.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    subprocess.Popen(
        [sys.executable, script_path], 
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env_vars
    )
    return {"status": "success"}

@app.post("/api/open")
def open_resume(req: OpenRequest):
    secure_filename = os.path.basename(req.filename)
    filepath = os.path.join(ROOT_DIR, "Tailored_Resumes", secure_filename)
    if os.path.exists(filepath):
        # Magically opens the file in MS Word!
        os.startfile(filepath)
        return {"status": "success"}
    return {"status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
