"""
rag/vector_store.py
ChromaDB vector store — local prototype.
Swap for watsonx.data / Milvus in IBM Cloud production.
"""

import chromadb
from chromadb.utils import embedding_functions
from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, EMBEDDING_MODEL


def get_client() -> chromadb.Client:
    """
    Returns a persistent ChromaDB client.
    Data survives between runs — ingest once, query many times.
    """
    return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def get_collection():
    """
    Returns the crisis knowledge base collection.
    Creates it if it does not exist.
    Uses sentence-transformers for local embedding.
    In production: replace with IBM watsonx.ai embedding endpoint.
    """
    client = get_client()
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )


def collection_size() -> int:
    return get_collection().count()
