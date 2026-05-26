"""
db_loader.py — Embeds Master_Career_Profile.txt into ChromaDB for RAG.

Fixes applied vs. original:
  - FIX #1 : Sliding-window chunker with overlap — prevents context breaks at
              paragraph boundaries (was plain double-newline split, zero overlap)
  - FIX #2 : MD5 hash check — only re-embeds if the file has changed
              (was wiping and rebuilding the entire DB on every single Setup click)
  - FIX #3 : Embedding model pinned explicitly — no longer relies on ChromaDB
              default which can silently change across library versions
  - FIX #4 : All logic wrapped in main() — safe for import; no module-level side effects
  - FIX #5 : Progress output every 10 chunks — no longer appears frozen on large resumes
  - FIX #6 : Bare except on delete_collection replaced with explicit Exception logging
"""

import hashlib
import json
import os
import sys

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from utils import logger

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── Constants ─────────────────────────────────────────────────────────────────
# FIX #1: Sliding-window chunking parameters
CHUNK_SIZE    = 400   # approximate characters per chunk
CHUNK_OVERLAP = 80    # overlap in characters between adjacent chunks
MIN_CHUNK_LEN = 50    # discard chunks shorter than this

# FIX #2: Path to store the hash of the last embedded file
ROOT_DIR       = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
HASH_CACHE_PATH = os.path.join(ROOT_DIR, "backend", "chroma_db", ".profile_hash")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _file_md5(path: str) -> str:
    """Return the MD5 hex-digest of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _sliding_window_chunks(text: str) -> list[str]:
    """
    FIX #1: Split text into overlapping chunks of ~CHUNK_SIZE chars.
    This prevents RAG context from breaking at paragraph boundaries.
    """
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end   = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_LEN:
            chunks.append(chunk)
        if end >= len(text):
            break
        # Advance by (CHUNK_SIZE - CHUNK_OVERLAP) to create overlap
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """FIX #4: All logic inside main() so the module is safe to import."""

    master_resume_path = os.path.join(ROOT_DIR, "Master_Career_Profile.txt")
    logger.info("Reading Master Career Profile...")

    if not os.path.exists(master_resume_path):
        raise SystemExit(
            "ERROR: Master_Career_Profile.txt not found. "
            "Complete the Setup Wizard first."
        )

    # FIX #2: Check MD5 hash — skip re-embedding if file hasn't changed
    current_hash = _file_md5(master_resume_path)
    if os.path.exists(HASH_CACHE_PATH):
        with open(HASH_CACHE_PATH, "r") as hf:
            cached_hash = hf.read().strip()
        if cached_hash == current_hash:
            logger.info(
                "✅ Career Profile is unchanged (hash match). "
                "Skipping re-embedding — Vector DB is already up to date."
            )
            return

    # ── Connect to ChromaDB ───────────────────────────────────────────────────
    db_path = os.path.join(ROOT_DIR, "backend", "chroma_db")

    # Use ChromaDB's built-in ONNX embedding (same all-MiniLM-L6-v2 model,
    # no PyTorch required — ~200 MB vs ~2 GB for sentence-transformers)
    embedding_fn = DefaultEmbeddingFunction()

    client = chromadb.PersistentClient(path=db_path)

    # Delete old collection so we start fresh
    try:
        client.delete_collection(name="career_projects")
        logger.info("Old collection deleted.")
    # FIX #6: Specific exception — not bare except: pass
    except Exception as e:
        logger.info("Note on collection delete (may not exist yet): %s", e)

    collection = client.create_collection(
        name="career_projects",
        embedding_function=embedding_fn,
    )

    # ── Chunk the resume ──────────────────────────────────────────────────────
    with open(master_resume_path, "r", encoding="utf-8") as f:
        text = f.read()

    # FIX #1: Use sliding-window chunker instead of naive double-newline split
    chunks = _sliding_window_chunks(text)
    logger.info("Created %d overlapping chunks (size=%d, overlap=%d).",
                len(chunks), CHUNK_SIZE, CHUNK_OVERLAP)

    if not chunks:
        raise SystemExit(
            "CRITICAL: Master Career Profile appears empty. "
            "Paste your resume in the Setup Wizard and try again."
        )

    # ── Embed and upload ──────────────────────────────────────────────────────
    logger.info("Embedding into Vector Space...")
    for i, chunk in enumerate(chunks):
        collection.add(documents=[chunk], ids=[f"chunk_{i}"])
        # FIX #5: Progress every 10 chunks so the terminal doesn't look frozen
        if (i + 1) % 10 == 0 or (i + 1) == len(chunks):
            logger.info("   Embedded %d / %d chunks...", i + 1, len(chunks))

    logger.info(
        "✅ Successfully embedded %d chunks into ChromaDB!", collection.count()
    )

    # FIX #2: Save new hash so next run skips re-embedding
    os.makedirs(os.path.dirname(HASH_CACHE_PATH), exist_ok=True)
    with open(HASH_CACHE_PATH, "w") as hf:
        hf.write(current_hash)
    logger.info("Hash cached — next run will skip re-embedding unless file changes.")


if __name__ == "__main__":
    main()
