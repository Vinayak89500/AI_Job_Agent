import os
import re
import sys
import csv
import docx  
import json
import time
import chromadb
from openai import OpenAI
from dotenv import load_dotenv

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

# 1. Setup API
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
config_path = os.path.join(root_dir, 'config.json')

if not os.path.exists(config_path):
    print("Error: Could not find config.json! Please complete the Setup Wizard on the UI.")
    exit(1)

with open(config_path, "r", encoding="utf-8") as f:
    config_data = json.load(f)

api_key = config_data.get("groqApiKey")
if not api_key:
    print("Error: Could not find GROQ_API_KEY in your config.json!")
    exit(1)

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=api_key,
)

# 2. Connect to Vector Database
print("Connecting to Vector Database...")
db_path = os.path.join(root_dir, "backend", "chroma_db")
try:
    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_collection(name="career_projects")
except Exception as e:
    print(f"Error connecting to ChromaDB: {e}")
    print("Please run db_loader.py first to embed your projects!")
    exit(1)

# 3. Process the Jobs Database
csv_file = os.path.join(root_dir, "jobs_database.csv")
if not os.path.isfile(csv_file):
    print("Could not find jobs_database.csv! Run the scraper first.")
    exit(1)

# Create an output folder to store your beautiful new resumes
output_dir = os.path.join(root_dir, "Tailored_Resumes")
os.makedirs(output_dir, exist_ok=True)

print("\n--- Starting End-to-End Generation ---\n")

# Open the CSV and read the jobs
with open(csv_file, mode='r', encoding='utf-8') as file:
    reader = csv.reader(file)
    header = next(reader, None)  # Skip the header row
    
    for row in reader:
        # We now have 5 columns!
        if len(row) < 5:
            continue
            
        job_title = row[0]
        company = row[1]
        link = row[2]
        apply_type = row[3]
        job_description = clean_job_description(row[4])
        
        # --- ONLY ADD COMPANY WEBSITE JOBS ---
        if apply_type != "Company Website":
            continue
        safe_company = re.sub(r'[\\/*?:"<>|]', "_", company).replace(" ", "_")
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", job_title).replace(" ", "_")
        filename = f"{safe_company}_{safe_title}.md"
        filepath = os.path.join(output_dir, filename)
        
        docx_filename = filename.replace('.md', '.docx')
        docx_filepath = os.path.join(output_dir, docx_filename)
        
        # Smart Feature: Skip if we already generated it AND the Word doc exists!
        if os.path.exists(filepath) and os.path.exists(docx_filepath):
            print(f"Skipping {company} - Resume already generated!")
            continue
            
        print(f"Generating custom resume for {company} - {job_title}...")
        
        # --- DYNAMIC VECTOR RAG ---
        print(f"   -> Querying Vector DB for top 3 projects matching this specific job...")
        results = collection.query(
            query_texts=[job_description],
            n_results=3
        )
        retrieved_projects = "\n\n".join(results['documents'][0])
        
        # Build the dynamic resume payload
        master_resume_path = os.path.join(root_dir, "Master_Career_Profile.txt")
        with open(master_resume_path, "r", encoding="utf-8") as f:
            base_resume = f.read()
            
        my_real_resume = f"""
## CANDIDATE MASTER CAREER PROFILE
{base_resume}

## HIGH-RELEVANCE FOCAL POINTS (Retrieved from Candidate's Background for this JD)
{retrieved_projects}
"""
        
        try:
            # 1. Send it to the Brain to Tailor!
            max_retries = 3
            model_to_use = "llama-3.3-70b-versatile"
            response = None
            for attempt in range(max_retries):
                try:
                    response = client.chat.completions.create(
                        model=model_to_use,
                        max_tokens=1500,
                        temperature=0.5,
                        messages=[
                            {
                                "role": "system", 
                                "content": f"""You are an expert tech recruiter and master resume writer. 
Your task is to craft a highly targeted 1-page resume using the candidate's Master Profile and the provided high-relevance focal points.

CRITICAL RULES:
1. FORMATTING: You MUST use these exact section headers: 
   {config_data.get("fullName", "User Name")} (Contact Info block below it)
   PROFESSIONAL SUMMARY
   CORE COMPETENCIES
   PROFESSIONAL EXPERIENCE
   INTERNSHIP
   EDUCATION
   CERTIFICATIONS & PROFESSIONAL DEVELOPMENT
   ADDITIONAL
2. CONTACT INFO: Always use this exact contact block at the top:
   {config_data.get("cityCountry", "City, Country")} | {config_data.get("phone", "Phone")} | {config_data.get("email", "Email")} | {config_data.get("linkedin", "LinkedIn")}
3. RAG INTEGRATION: Use the "CANDIDATE MASTER CAREER PROFILE" as the absolute source of truth. The "HIGH-RELEVANCE FOCAL POINTS" are specific sections from the candidate's real background that match the target job description. Give these focal points extra prominence and detail when drafting the resume.
4. PRODUCT MANAGEMENT TRANSLATION: Translate the candidate's engineering achievements (e.g., CAD design, BOM management, mechanical simulation, PLM work) into product management terminology and outcomes (e.g., user-centric design, requirements engineering, product discovery, cross-functional delivery, stakeholder alignment, cycle-time optimization).
5. STRICT HONESTY & EVIDENCE RULE: Every single skill, tool, framework, domain term, or keyword you add to the Professional Summary, Core Competencies, or Professional Experience MUST have a direct, verifiable foundation in the Candidate's Master Profile. Do NOT invent certifications, project names, or direct work experience in domains (like cybersecurity, data governance, or fintech) where the candidate has no matching foundation in their Master Profile.
6. NO PLACEHOLDERS or extra 'Notes' at the bottom. Make it a final, polished resume."""
                            },
                            {
                                "role": "user",
                                "content": f"CANDIDATE PROFILE DATA:\n{my_real_resume}\n\nTARGET CLEAN JOB DESCRIPTION:\n{job_description}\n\nBuild my tailored 1-page resume to perfectly match this job."
                            }
                        ]
                    )
                    break
                except Exception as api_err:
                    if model_to_use == "llama-3.3-70b-versatile":
                        print(f"   -> Groq 70B model failed or rate-limited. Falling back to llama-3.1-8b-instant...")
                        model_to_use = "llama-3.1-8b-instant"
                        continue
                    if attempt < max_retries - 1:
                        print(f"   -> API Rate Limit Hit! Sleeping for 20 seconds before retrying (Attempt {attempt+1}/{max_retries})...")
                        time.sleep(20)
                    else:
                        raise api_err
            
            tailored_content = response.choices[0].message.content            

            # 2. Score the Resume
            print(f"   -> Scoring resume for {company}...")
            eval_response = None
            eval_model = "llama-3.3-70b-versatile"
            for attempt in range(max_retries):
                try:
                    eval_response = client.chat.completions.create(
                        model=eval_model,
                        max_tokens=1000,
                        response_format={ "type": "json_object" },
                        temperature=0.0,
                        messages=[
                            {
                                "role": "system", 
                                "content": """You are a cynical, highly critical senior principal recruiter and ATS (Applicant Tracking System) scanner.
Evaluate the provided candidate resume against the provided job description.
You MUST output your evaluation in strict JSON format with exactly these keys:
{
  "overall_score": <int 0-100>,
  "missing_keywords": [<list of important missing keywords>],
  "feedback": "<Provide 2-3 actionable sentences suggesting exactly how the user can edit their resume to organically include these missing keywords>"
}

STRICT EVALUATION CRITERIA:
1. KEYWORD MATCH: Check if keywords from the job description are present in the resume.
2. EVIDENCE VERIFICATION: Do NOT award score points for keywords listed in the 'Professional Summary' or 'Core Competencies' if they are NOT backed up by concrete projects or experience bullet points. If you detect keyword stuffing without evidence, DOCK the overall score by 10 points per occurrence.
3. DOMAIN ALIGNMENT: Deduct points if there is a mismatch between the candidate's industry background and the job's domain. For generalist/entry-level roles (like Associate Product Manager or Product Analyst), be lenient, as transferable engineering, analytical, and digital transformation skills are highly valued. Only deduct points heavily (resulting in scores below 65) if the role is in a highly specialized technical domain (like Cybersecurity, Cloud SecOps, Medical Devices) where the candidate completely lacks the required domain-specific work experience or credentials.
4. BE HONEST & CRITICAL: A perfect resume is rare. Do not give scores above 85 unless there is authentic, high-quality, evidence-backed alignment."""
                            },
                            {
                                "role": "user",
                                "content": f"Job Description:\n{job_description}\n\nCandidate Resume:\n{tailored_content}"
                            }
                        ]
                    )
                    break
                except Exception as api_err:
                    if eval_model == "llama-3.3-70b-versatile":
                        print(f"   -> Groq 70B evaluation model failed or rate-limited. Falling back to llama-3.1-8b-instant...")
                        eval_model = "llama-3.1-8b-instant"
                        continue
                    if attempt < max_retries - 1:
                        print(f"   -> API Rate Limit Hit on Scoring! Sleeping for 20 seconds before retrying (Attempt {attempt+1}/{max_retries})...")
                        time.sleep(20)
                    else:
                        raise api_err
            
            # Parse the JSON score securely (handling LLM hallucinations)
            try:
                raw_eval_text = eval_response.choices[0].message.content
                # Use regex to extract JSON just in case the LLM added conversational text like "Here is the JSON: {}"
                json_match = re.search(r'\{.*\}', raw_eval_text, re.DOTALL)
                if json_match:
                    eval_data = json.loads(json_match.group())
                else:
                    eval_data = json.loads(raw_eval_text)
                    
                score = eval_data.get('overall_score', 0)
                missing = ", ".join(eval_data.get('missing_keywords', []))
                feedback = eval_data.get('feedback', 'No suggestions provided.')
            except Exception as json_err:
                print(f"   -> ⚠️ Warning: Failed to parse LLM evaluation JSON ({json_err}). Using defaults.")
                score = "N/A"
                missing = "Unknown"
                feedback = "LLM failed to provide structured feedback."
            
            # 3. Save it to a Markdown file with the Score at the top!
            with open(filepath, 'w', encoding='utf-8') as out_file:
                out_file.write(f"**Target Company:** {company}\n")
                out_file.write(f"**Job Link:** {link}\n")
                out_file.write(f"**Apply Type:** {apply_type}\n")  # Added Apply Type here!
                out_file.write(f"**ATS Score:** {score}/100\n")
                out_file.write(f"**Missing Keywords:** {missing}\n")
                out_file.write(f"**Suggestions:** {feedback}\n\n")
                out_file.write("---\n\n")
                out_file.write(tailored_content)
                
            # 4. Save a .docx version for the user to edit!
            docx_filename = filename.replace(".md", ".docx")
            docx_filepath = os.path.join(output_dir, docx_filename)
            
            doc = docx.Document()
                
            # Robust text injection with Markdown bold parser
            title_p = doc.add_paragraph(f"Resume: {company} - {job_title}")
            if title_p.runs: title_p.runs[0].bold = True
            
            def add_markdown_paragraph(doc_obj, text, style=None):
                p = doc_obj.add_paragraph(style=style)
                parts = re.split(r'(\*\*.*?\*\*)', text)
                for part in parts:
                    if part.startswith('**') and part.endswith('**'):
                        p.add_run(part[2:-2]).bold = True
                    else:
                        p.add_run(part)
                return p
            
            for line in tailored_content.split('\n'):
                line_clean = line.strip()
                if line_clean.startswith('# '):
                    p = add_markdown_paragraph(doc, line_clean[2:])
                    for r in p.runs: r.bold = True
                elif line_clean.startswith('## '):
                    p = add_markdown_paragraph(doc, line_clean[3:])
                    for r in p.runs: r.bold = True
                elif line_clean.startswith('### '):
                    p = add_markdown_paragraph(doc, line_clean[4:])
                    for r in p.runs: r.bold = True
                elif line_clean.startswith('- ') or line_clean.startswith('* '):
                    try: 
                        add_markdown_paragraph(doc, line_clean[2:], style='List Paragraph')
                    except:
                        try: 
                            add_markdown_paragraph(doc, line_clean[2:], style='List Bullet')
                        except: 
                            add_markdown_paragraph(doc, '• ' + line_clean[2:])
                elif line_clean == "":
                    continue
                else:
                    add_markdown_paragraph(doc, line_clean)
                    
            doc.save(docx_filepath)
                
            print(f"-> SUCCESS! Scored {score}/100. Saved to Tailored_Resumes/{docx_filename}\n")
            
            # Anti-Rate Limit Protection: Pause for 3 seconds to keep Groq happy (30 RPM limit)
            time.sleep(3)
            
        except Exception as e:
            print(f"-> Failed to generate for {company}: {e}\n")

print("All done! Open the Tailored_Resumes folder in VS Code to see your files!")
