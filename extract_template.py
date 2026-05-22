import docx
import os

root_dir = os.path.dirname(os.path.abspath(__file__))
doc_path = os.path.join(root_dir, "Template_Resume.docx")
txt_path = os.path.join(root_dir, "template_text.txt")

try:
    doc = docx.Document(doc_path)
    text = []
    for p in doc.paragraphs:
        text.append(p.text)
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    print("Successfully extracted text!")
except Exception as e:
    print(f"Error: {e}")
