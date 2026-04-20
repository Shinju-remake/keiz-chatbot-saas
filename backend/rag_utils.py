import os
import sys
from typing import List, Optional

def get_collection(company_id: int, api_key: Optional[str] = None):
    """
    ULTRA-LAZY LOADING: Only imports chromadb when a search is actually performed.
    This prevents Render from hanging during the build/startup phase.
    """
    try:
        # Check for production shim
        try:
            __import__('pysqlite3')
            sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
        except ImportError:
            pass

        import chromadb
        from chromadb.utils import embedding_functions

        CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        
        api_key = api_key or os.getenv("OPENAI_API_KEY", "placeholder")
        emb_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name="text-embedding-3-small"
        )
        
        collection_name = f"company_{company_id}_kb"
        return client.get_or_create_collection(name=collection_name, embedding_function=emb_fn)
    except Exception as e:
        print(f"⚠️ RAG ENGINE UNAVAILABLE: {e}")
        return None

def index_knowledge_base(company_id: int, text: str, api_key: Optional[str] = None):
    try:
        collection = get_collection(company_id, api_key)
        if not collection: return
        
        chunks = [c.strip() for c in text.split("\n") if len(c.strip()) > 20]
        if not chunks: chunks = [text]
            
        ids = [f"chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"company_id": company_id} for _ in chunks]
        
        try: collection.delete(where={"company_id": company_id})
        except: pass
            
        collection.add(documents=chunks, ids=ids, metadatas=metadatas)
        print(f"✅ RAG Indexed for Company {company_id}")
    except Exception as e:
        print(f"❌ RAG INDEX ERROR: {e}")

def search_kb(company_id: int, query: str, api_key: Optional[str] = None, n_results: int = 3) -> str:
    try:
        collection = get_collection(company_id, api_key)
        if not collection: return ""
        
        results = collection.query(query_texts=[query], n_results=n_results)
        if results['documents'] and results['documents'][0]:
            return "\n".join(results['documents'][0])
    except Exception as e:
        print(f"⚠️ RAG SEARCH FALLBACK: {e}")
    return ""
