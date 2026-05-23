import sys
import os
import chromadb

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Initialize Local Vector Database
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
db_path = os.path.join(root_dir, "backend", "chroma_db")
client = chromadb.PersistentClient(path=db_path)

# 2. Create or reset the collection
try:
    client.delete_collection(name="career_projects")
except:
    pass
collection = client.create_collection(name="career_projects")

# 3. Read and Chunk the Master Career Profile dynamically
master_resume_path = os.path.join(root_dir, "Master_Career_Profile.txt")
print("Reading Master Career Profile...")

if not os.path.exists(master_resume_path):
    print("Error: Master_Career_Profile.txt not found! Please complete the Setup Wizard.")
    exit(1)

with open(master_resume_path, "r", encoding="utf-8") as f:
    text = f.read()

# Chunk the resume by double newlines (paragraphs/sections)
chunks = [chunk.strip() for chunk in text.split("\n\n") if len(chunk.strip()) > 50]

print(f"Found {len(chunks)} distinct experience/project chunks.")

if not chunks:
    print("\n🚨 CRITICAL ERROR: Your Master Career Profile appears to be empty or improperly formatted.")
    print("We need at least some text (paragraphs > 50 characters) to embed into the AI Brain.")
    print("Please go to the Setup Wizard, paste your massive master resume, and try again!")
    exit(1)
# 4. Mathematically Embed and Upload to ChromaDB
print("Embedding into Vector Space... (This will download a small local AI model the first time)")
for i, chunk in enumerate(chunks):
    collection.add(
        documents=[chunk],
        ids=[f"chunk_{i}"]
    )

print(f"Successfully embedded {collection.count()} chunks into ChromaDB!")