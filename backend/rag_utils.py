import chromadb
from chromadb.utils import embedding_functions
import os
from typing import List, Optional

# Initialize ChromaDB persistent client
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
client = chromadb.PersistentClient(path=CHROMA_PATH)

# Switch to OpenAI Embeddings (Lightweight, No Torch/Sentence-Transformers needed on server)
def get_emb_fn(company_api_key: Optional[str] = None):
    api_key = company_api_key or os.getenv("OPENAI_API_KEY")
    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name="text-embedding-3-small"
    )

def get_collection(company_id: int, api_key: Optional[str] = None):
    """
    Returns a unique collection for each company (tenant isolation).
    """
    collection_name = f"company_{company_id}_kb"
    return client.get_or_create_collection(name=collection_name, embedding_function=get_emb_fn(api_key))

def index_knowledge_base(company_id: int, text: str, api_key: Optional[str] = None):
    """
    Chunks the knowledge base text and indexes it in the vector DB.
    """
    collection = get_collection(company_id, api_key)
    
    # Simple chunking logic (by paragraph/new lines)
    chunks = [c.strip() for c in text.split("\n") if len(c.strip()) > 20]
    if not chunks:
        chunks = [text] # Fallback if no newlines
        
    ids = [f"chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"company_id": company_id} for _ in chunks]
    
    # Delete old data for this company before re-indexing
    try:
        collection.delete(where={"company_id": company_id})
    except:
        pass
        
    collection.add(
        documents=chunks,
        ids=ids,
        metadatas=metadatas
    )
    print(f"✅ RAG (OpenAI): Indexed {len(chunks)} chunks for Company {company_id}")

def search_kb(company_id: int, query: str, api_key: Optional[str] = None, n_results: int = 3) -> str:
    """
    Performs semantic search to find the most relevant context for a query.
    """
    try:
        collection = get_collection(company_id, api_key)
        results = collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        if results['documents'] and results['documents'][0]:
            return "\n".join(results['documents'][0])
    except Exception as e:
        print(f"RAG SEARCH ERROR: {e}")
    
    return ""
