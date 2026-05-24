import os
import json
import chromadb
from openai import OpenAI

def evaluate_retrieval(retrieved_text, expected_keywords):
    """Calculates Context Recall based on presence of expected keywords."""
    retrieved_text_lower = retrieved_text.lower()
    matches = 0
    for kw in expected_keywords:
        if kw.lower() in retrieved_text_lower:
            matches += 1
            
    if len(expected_keywords) == 0:
        return 100
    
    score = (matches / len(expected_keywords)) * 100
    return round(score)

def evaluate_generation(client, jd, retrieved_context, generated_text):
    """Uses LLM-as-a-judge to evaluate Faithfulness and Relevance."""
    eval_prompt = f"""You are an MLOps Evaluation Judge.
Evaluate the 'Generated Resume Section' based on two strict metrics:
1. FAITHFULNESS (0-100): Did the generation ONLY use facts present in the 'Retrieved Context'? Hallucinations or invented facts score 0.
2. RELEVANCE (0-100): Does the generation actually address the needs of the 'Job Description'?

Job Description:
{jd}

Retrieved Context:
{retrieved_context}

Generated Resume Section:
{generated_text}

Respond strictly in JSON format:
{{"faithfulness": <score>, "relevance": <score>, "reasoning": "<short explanation>"}}
"""
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": eval_prompt}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error during LLM evaluation: {e}")
        return {"faithfulness": 0, "relevance": 0, "reasoning": "Evaluation failed."}

def run_evaluation():
    print("===================================================")
    print("    AI Job Agent - MLOps Evaluation Suite")
    print("===================================================\n")
    
    # 1. Setup Clients
    root_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(root_dir, 'config.json')
    
    if not os.path.exists(config_path):
        print("Error: config.json not found. Run the UI setup first.")
        return
        
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        
    api_key = config_data.get("groqApiKey")
    if not api_key:
        print("Error: GROQ_API_KEY missing from config.")
        return
        
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    
    try:
        db_path = os.path.join(root_dir, "backend", "chroma_db")
        chroma_client = chromadb.PersistentClient(path=db_path)
        collection = chroma_client.get_collection(name="career_projects")
    except Exception as e:
        print("Error connecting to ChromaDB. Did you run db_loader.py?")
        return
        
    # 2. Load Golden Dataset
    dataset_path = os.path.join(os.path.dirname(__file__), "golden_dataset.json")
    with open(dataset_path, "r") as f:
        test_cases = json.load(f)
        
    # 3. Run Pipeline
    total_retrieval = 0
    total_faithfulness = 0
    total_relevance = 0
    
    for tc in test_cases:
        print(f"Running Test Case: {tc['id']} - {tc['job_title']}")
        
        # --- A. Evaluate Retrieval ---
        results = collection.query(
            query_texts=[tc['job_description']],
            n_results=3
        )
        retrieved_text = "\n\n".join(results['documents'][0])
        
        retrieval_score = evaluate_retrieval(retrieved_text, tc['expected_retrieval_keywords'])
        total_retrieval += retrieval_score
        print(f"  [Retrieval] Context Recall Score: {retrieval_score}/100")
        
        # --- B. Generate Resume Section ---
        gen_prompt = f"""Write a 3-bullet professional summary for a {tc['job_title']} role using ONLY the following retrieved background context. Do not invent any skills.
Context:
{retrieved_text}"""
        
        try:
            gen_resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": gen_prompt}],
                temperature=0.3
            )
            generated_text = gen_resp.choices[0].message.content
        except Exception as e:
            print(f"  [Generation] Failed: {e}")
            continue
            
        # --- C. Evaluate Generation ---
        eval_metrics = evaluate_generation(client, tc['job_description'], retrieved_text, generated_text)
        total_faithfulness += eval_metrics.get("faithfulness", 0)
        total_relevance += eval_metrics.get("relevance", 0)
        
        print(f"  [Generation] Faithfulness Score: {eval_metrics.get('faithfulness', 0)}/100")
        print(f"  [Generation] Relevance Score:    {eval_metrics.get('relevance', 0)}/100")
        print(f"  [Evaluation Note] {eval_metrics.get('reasoning', '')}\n")
        
    # 4. Final Report
    n = len(test_cases)
    print("===================================================")
    print("    EVALUATION COMPLETE")
    print("===================================================")
    print(f"Average Retrieval Score:   {round(total_retrieval/n)}/100")
    print(f"Average Faithfulness Score: {round(total_faithfulness/n)}/100")
    print(f"Average Relevance Score:    {round(total_relevance/n)}/100")

if __name__ == "__main__":
    run_evaluation()
