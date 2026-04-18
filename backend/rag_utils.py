import os
import sys
from typing import List, Optional

# PRODUCTION SHIM: Force ChromaDB to use a compatible SQLite binary on Render
try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

import chromadb
from chromadb.utils import embedding_functions

# Initialize ChromaDB with a safe path for Render
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")

def get_client():
    """Lazy initialization of the Chroma client."""
    return chromadb.PersistentClient(path=CHROMA_PATH)

def get_emb_fn(company_api_key: Optional[str] = None):
    api_key = company_api_key or os.getenv("OPENAI_API_KEY", "placeholder")
    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name="text-embedding-3-small"
    )

def get_collection(company_id: int, api_key: Optional[str] = None):
    """Returns a unique collection for each company."""
    client = get_client()
    collection_name = f"company_{company_id}_kb"
    return client.get_or_create_collection(name=collection_name, embedding_function=get_emb_fn(api_key))

def index_knowledge_base(company_id: int, text: str, api_key: Optional[str] = None):
    """Indexes text in the vector DB."""
    try:
        collection = get_collection(company_id, api_key)
        chunks = [c.strip() for c in text.split("\n") if len(c.strip()) > 20]
        if not chunks: chunks = [text]
            
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"company_id": company_id} for _ in chunks]
        
        try:
            collection.delete(where={"company_id": company_id})
        except:
            pass
            
        collection.add(documents=chunks, ids=ids, metadatas=metadatas)
        print(f"✅ RAG (OpenAI): Indexed {len(chunks)} chunks for Company {company_id}")
    except Exception as e:
        print(f"❌ RAG INDEX ERROR: {e}")

def search_kb(company_id: int, query: str, api_key: Optional[str] = None, n_results: int = 3) -> str:
    """Performs semantic search."""
    try:
        collection = get_collection(company_id, api_key)
        results = collection.query(query_texts=[query], n_results=n_results)
        if results['documents'] and results['documents'][0]:
            return "\n".join(results['documents'][0])
    except Exception as e:
        print(f"⚠️ RAG SEARCH FALLBACK: {e}")
    return ""
