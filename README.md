# 🤖 AI Job Application Agent

An **Autonomous, Local-First AI Agent** that completely automates the modern job search process. 

This tool uses Asynchronous Web Scraping (Playwright) to find jobs, a Vector Database (ChromaDB) to mathematically embed your past projects, and a Dual-Agent LLM system (Llama-3.1 via Groq) to tailor a pixel-perfect, native Microsoft Word (`.docx`) resume for every single application.

## 🌟 Features
* **Web Engine:** Asynchronous Playwright scraping with DOM Hydration locking and randomized "human breathing" delays to bypass bot detection.
* **Vector RAG (Retrieval-Augmented Generation):** Embeds your `Master_Career_Profile.txt` into a local ChromaDB instance to prevent LLM hallucination and ensure factual accuracy.
* **Dual-Agent Evaluator System:** 
  * *Agent 1 (The Writer):* Drafts the tailored resume based on the Job Description.
  * *Agent 2 (The Scorer):* An adversarial ATS-Persona that strictly grades the draft out of 100 to ensure high keyword matching.
* **Dynamic Generation:** Natively outputs recruiter-ready `.docx` files using `python-docx`.
* **Zero Cloud Liability:** 100% Local-First architecture. Your Naukri credentials and personal data never leave your machine.
* **Zero API Cost:** Inference runs locally via the Groq LPU API.

---

## 🚀 Quick Start Guide

### Option 1: The 1-Click Windows Installer (Recommended)
If you are on Windows, you don't need to touch the terminal!
1. Download or clone this repository.
2. Double-click the **`Start_Job_Agent.bat`** file.
3. It will automatically install Python dependencies, set up the headless browsers, boot the server, and open the dashboard in your default web browser!

### Option 2: Manual Installation (Mac / Linux)
Ensure you have Python 3.10+ installed. Open your terminal and run:

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install

# 2. Boot the Agent
python backend/app/api.py
```
Then, open your browser and navigate to: **`http://localhost:8000`**

On your first launch, the **Setup Wizard** will automatically appear. 
1. Enter your Name, Contact Info, and Groq API Key.
2. Paste your massive Master Resume into the text box.
3. Click "Save Settings & Initialize Vector DB".

The backend will automatically save your `config.json` and mathematically embed your resume into Vector space. You are now ready to automate your job search!

---

## 🛠 Architecture

* **Frontend:** Vanilla JS / HTML / TailwindCSS
* **Backend:** FastAPI (Python)
* **Web Scraper:** Playwright Async
* **Vector DB:** ChromaDB (`all-MiniLM-L6-v2`)
* **Inference Engine:** Groq (Llama-3.1-8b-instant)

## ⚠️ Disclaimer
This tool is for educational purposes. Use responsibly and ensure you comply with the Terms of Service of any job boards you interact with.
