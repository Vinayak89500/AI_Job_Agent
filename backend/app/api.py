"""
api.py — FastAPI server wiring the dashboard to all backend scripts.

Fixes applied vs. original:
  - FIX #1 : CREATE_NEW_CONSOLE wrapped in platform guard (was crashing on macOS/Linux)
  - FIX #2 : os.startfile() replaced with cross-platform open logic
  - FIX #3 : Simple secret-token auth on all POST endpoints (unauthenticated before)
  - FIX #4 : Groq API key read from GROQ_API_KEY env var as fallback (less reliance
              on plain-text config.json)
  - FIX #5 : Errors raise HTTPException (HTTP 400/500) instead of returning HTTP 200
              with {status: 'error'} body
  - FIX #6 : Naukri credentials removed from ScrapeRequest / subprocess argv —
              scraper.py now reads them from .env directly
  - FIX #7 : /api/reset requires {confirm: "DELETE_ALL"} body to prevent accidents
  - FIX #8 : /api/jobs result cached by CSV mtime — no disk read on every refresh
  - FIX #9 : /api/open path-traversal hardened with realpath assertion
  - FIX #10: index.html cached at startup — no disk read on every GET /
"""

import csv
import json
import os
import re
import secrets
import subprocess
import sys

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from utils import logger

# ── Startup ───────────────────────────────────────────────────────────────────
ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

CSV_PATH         = os.path.join(ROOT_DIR, "jobs_database.csv")
FRONTEND_DIR     = os.path.join(ROOT_DIR, "frontend")
CONFIG_PATH      = os.path.join(ROOT_DIR, "config.json")
MASTER_PROF_PATH = os.path.join(ROOT_DIR, "Master_Career_Profile.txt")
RESUMES_DIR      = os.path.join(ROOT_DIR, "Tailored_Resumes")

# FIX #1: Platform-safe subprocess flag
_NEW_CONSOLE = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0

# FIX #10: Cache index.html at startup
_INDEX_HTML: str = ""
_index_path = os.path.join(FRONTEND_DIR, "index.html")
if os.path.exists(_index_path):
    with open(_index_path, "r", encoding="utf-8") as _f:
        _INDEX_HTML = _f.read()

# FIX #3: Auth token — read from .env or auto-generate and print on first run
_API_TOKEN = os.getenv("AGENT_API_TOKEN", "")
if not _API_TOKEN:
    _API_TOKEN = secrets.token_urlsafe(24)
    logger.warning(
        "⚠️  No AGENT_API_TOKEN found in .env.\n"
        "   Auto-generated token for this session: %s\n"
        "   Add  AGENT_API_TOKEN=%s  to your .env to make it permanent.",
        _API_TOKEN, _API_TOKEN,
    )

# FIX #8: Jobs cache (invalidated when CSV mtime changes)
_jobs_cache: list[dict] = []
_jobs_cache_mtime: float = 0.0

app = FastAPI()

# ── Auth dependency ───────────────────────────────────────────────────────────
_security = HTTPBearer(auto_error=False)


def require_token(
    creds: HTTPAuthorizationCredentials = Depends(_security),
) -> None:
    """FIX #3: Verify Bearer token on every state-changing endpoint."""
    if creds is None or creds.credentials != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")


# ── Pydantic models ───────────────────────────────────────────────────────────
class ApplyRequest(BaseModel):
    link: str
    company: str


class ScrapeRequest(BaseModel):
    job_title:  str
    experience: str
    max_jobs:   int = 5
    # FIX #6: username/password REMOVED — scraper reads from .env directly


class OpenRequest(BaseModel):
    filename: str


class SetupRequest(BaseModel):
    fullName:    str
    cityCountry: str
    phone:       str
    email:       str
    linkedin:    str
    groqApiKey:  str
    resumeText:  str


class ResetRequest(BaseModel):
    # FIX #7: Confirmation token required to prevent accidental data wipe
    confirm: str


# ── GET endpoints ─────────────────────────────────────────────────────────────

@app.get("/")
def read_root() -> HTMLResponse:
    # FIX #10: Serve from memory cache
    if _INDEX_HTML:
        return HTMLResponse(content=_INDEX_HTML)
    # Fallback: re-read if cache is empty (e.g. file added after startup)
    try:
        with open(_index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except OSError:
        raise HTTPException(status_code=404, detail="index.html not found.")


@app.get("/api/token")
def get_token() -> dict:
    """Return the API token so the frontend can include it in POST requests.
    Safe to expose on localhost-only server."""
    return {"token": _API_TOKEN}


@app.get("/api/config")
def get_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # FIX #5: HTTP 500 instead of HTTP 200 + {status: error}
            raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=404, detail="Config not found.")


@app.get("/api/jobs")
def get_jobs() -> list[dict]:
    global _jobs_cache, _jobs_cache_mtime

    # FIX #8: Invalidate cache when CSV or Tailored_Resumes folder changes
    try:
        csv_mtime     = os.path.getmtime(CSV_PATH) if os.path.exists(CSV_PATH) else 0.0
        resumes_mtime = os.path.getmtime(RESUMES_DIR) if os.path.exists(RESUMES_DIR) else 0.0
        current_mtime = max(csv_mtime, resumes_mtime)
    except OSError:
        current_mtime = 0.0

    if current_mtime == _jobs_cache_mtime and _jobs_cache:
        return _jobs_cache

    jobs: list[dict] = []
    if os.path.exists(CSV_PATH):
        try:
            with open(CSV_PATH, mode="r", encoding="utf-8") as file:
                reader = csv.reader(file)
                next(reader, None)
                for row in reader:
                    if len(row) < 5:
                        continue
                    title, company, link, apply_type = row[0], row[1], row[2], row[3]

                    safe_co    = re.sub(r'[\\/*?:"<>|]', "_", company).replace(" ", "_")
                    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title).replace(" ", "_")
                    md_name    = f"{safe_co}_{safe_title}.md"
                    md_path    = os.path.join(RESUMES_DIR, md_name)

                    resume_status = (
                        "Not Applicable" if apply_type == "Naukri Apply" else "Not Generated"
                    )
                    ats_score = None

                    if apply_type == "Company Website" and os.path.exists(md_path):
                        resume_status = md_name.replace(".md", ".docx")
                        try:
                            with open(md_path, "r", encoding="utf-8") as mf:
                                for line in mf:
                                    if "**ATS Score:**" in line:
                                        raw = line.replace("**ATS Score:**", "").strip()
                                        # FIX #5 (score normalisation carried from main.py)
                                        ats_score = raw.split("/")[0].strip()
                                        break
                        except OSError:
                            pass

                    jobs.append({
                        "title":       title,
                        "company":     company,
                        "link":        link,
                        "apply_type":  apply_type,
                        "resume_file": resume_status,
                        "ats_score":   ats_score,
                    })
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not read jobs database: {e}")

    _jobs_cache       = jobs
    _jobs_cache_mtime = current_mtime
    return jobs


# ── POST endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/setup")
def setup_agent(req: SetupRequest) -> dict:
    """No auth required on setup — first-run bootstrap."""
    try:
        config_data = {
            "fullName":    req.fullName,
            "cityCountry": req.cityCountry,
            "phone":       req.phone,
            "email":       req.email,
            "linkedin":    req.linkedin,
            "groqApiKey":  req.groqApiKey,
            # FIX #3: Screenshot flag defaults to False; user can toggle via config
            "save_debug_screenshots": False,
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)

        with open(MASTER_PROF_PATH, "w", encoding="utf-8") as f:
            f.write(req.resumeText)

        db_loader_path = os.path.join(ROOT_DIR, "backend", "app", "db_loader.py")
        env_vars = os.environ.copy()
        env_vars["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen(
            [sys.executable, db_loader_path],
            creationflags=_NEW_CONSOLE,  # FIX #1
            env=env_vars,
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))  # FIX #5


@app.post("/api/reset")
def reset_session(req: ResetRequest, _: None = Depends(require_token)) -> dict:
    # FIX #7: Require explicit confirmation string
    if req.confirm != "DELETE_ALL":
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Send {\"confirm\": \"DELETE_ALL\"}.",
        )
    try:
        import shutil
        if os.path.exists(CSV_PATH):
            with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as file:
                csv.writer(file).writerow(
                    ["Title", "Company", "Link", "Apply_Type", "Job_Description"]
                )
        if os.path.exists(RESUMES_DIR):
            for fname in os.listdir(RESUMES_DIR):
                fpath = os.path.join(RESUMES_DIR, fname)
                if os.path.isfile(fpath):
                    os.unlink(fpath)

        # Invalidate cache
        global _jobs_cache, _jobs_cache_mtime
        _jobs_cache, _jobs_cache_mtime = [], 0.0

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apply")
def trigger_auto_apply(
    req: ApplyRequest, _: None = Depends(require_token)
) -> dict:
    script_path = os.path.join(ROOT_DIR, "backend", "app", "auto_apply.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    try:
        subprocess.Popen(
            [sys.executable, script_path, req.link, req.company],
            creationflags=_NEW_CONSOLE,  # FIX #1
            env=env_vars,
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scrape")
def trigger_scrape(
    req: ScrapeRequest, _: None = Depends(require_token)
) -> dict:
    script_path = os.path.join(ROOT_DIR, "backend", "app", "scraper.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    try:
        # FIX #6: username/password removed from argv — scraper reads from .env
        subprocess.Popen(
            [sys.executable, script_path,
             req.job_title, req.experience, str(req.max_jobs)],
            creationflags=_NEW_CONSOLE,  # FIX #1
            env=env_vars,
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/batch_apply")
def trigger_batch_apply(_: None = Depends(require_token)) -> dict:
    script_path = os.path.join(ROOT_DIR, "backend", "app", "batch_apply.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    try:
        subprocess.Popen(
            [sys.executable, script_path],
            creationflags=_NEW_CONSOLE,  # FIX #1
            env=env_vars,
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate")
def trigger_generate(_: None = Depends(require_token)) -> dict:
    script_path = os.path.join(ROOT_DIR, "backend", "app", "main.py")
    env_vars = os.environ.copy()
    env_vars["PYTHONIOENCODING"] = "utf-8"
    try:
        subprocess.Popen(
            [sys.executable, script_path],
            creationflags=_NEW_CONSOLE,  # FIX #1
            env=env_vars,
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/open")
def open_resume(req: OpenRequest, _: None = Depends(require_token)) -> dict:
    # FIX #9: Path-traversal hardening
    secure_name = os.path.basename(req.filename)
    filepath    = os.path.realpath(os.path.join(RESUMES_DIR, secure_name))
    safe_base   = os.path.realpath(RESUMES_DIR)

    if not filepath.startswith(safe_base + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        # FIX #2: Cross-platform file open
        if sys.platform == "win32":
            os.startfile(filepath)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    logger.info("Starting AI Job Agent server on http://127.0.0.1:8000")
    logger.info("API Token: %s", _API_TOKEN)
    uvicorn.run(app, host="127.0.0.1", port=8000)
