"""
rag/vector_store.py
Vector store access layer.
ChromaDB is the default local backend, with a backend switch for IBM Cloud migration.
"""

import chromadb
from chromadb.utils import embedding_functions
from config import (
    VECTOR_STORE_BACKEND,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    EMBEDDING_MODEL,
)


def get_client() -> chromadb.Client:
    """
    Returns a persistent ChromaDB client.
    Data survives between runs — ingest once, query many times.
    """
    if VECTOR_STORE_BACKEND != "chroma":
        raise NotImplementedError(
            f"Vector store backend '{VECTOR_STORE_BACKEND}' is not implemented yet. "
            "Set VECTOR_STORE_BACKEND=chroma to use the current local store."
        )
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
