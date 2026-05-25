"""
utils.py — Shared helpers for the AI Job Application Agent.
Centralising these here eliminates duplication across scraper.py and main.py.
"""

import re
import os
import logging

# ── Logging ──────────────────────────────────────────────────────────────────
# Configure once here; every other module does `from utils import logger`
# or creates its own child logger via logging.getLogger(__name__).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agent.log"),
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("job_agent")


# ── Job-description cleaner ───────────────────────────────────────────────────
# FIX (scraper.py #8 / main.py #9): was duplicated in both files.
# Now lives here and is imported by both.

START_MARKERS = [
    "Job description", "job description", "Job Description",
    "Job Highlights", "job highlights", "Job highlights",
]

END_MARKERS = [
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
    "HomeJobs in",
]


def clean_job_description(text: str) -> str:
    """Strip Naukri page boilerplate from a raw job page body text."""
    if not text:
        return ""

    # Find start of the actual description
    start_idx = -1
    for marker in START_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            start_idx = idx
            break

    text_desc = text[start_idx:] if start_idx != -1 else text

    # Find the end (cut footer noise)
    end_idx = len(text_desc)
    text_lower = text_desc.lower()
    for marker in END_MARKERS:
        idx = text_lower.find(marker.lower())
        if idx != -1 and idx < end_idx and idx > 100:
            end_idx = idx

    return text_desc[:end_idx].strip()


# ── Safe filename helper ───────────────────────────────────────────────────────
# FIX (auto_apply.py #4): replace() only removed spaces; this removes all
# characters that are illegal in Windows/Linux/macOS filenames.

def safe_filename(name: str) -> str:
    """Return a filesystem-safe version of a string (used for screenshot names)."""
    return re.sub(r"[^\w\-]", "_", name)
