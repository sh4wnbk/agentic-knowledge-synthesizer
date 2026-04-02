"""
agents/rag_knowledge_agent.py
Agent 3 — Memory & Knowledge Layer
Retrieval before reasoning — always.
Queries ChromaDB semantic vector store.
Key decision: sufficient confidence to proceed, or retry?
"""

from rag.retriever import Retriever
from config import CONFIDENCE_THRESHOLD


class RAGKnowledgeAgent:

    def __init__(self):
        self.retriever = Retriever(n_results=5)

    def retrieve(self, query: str) -> dict:
        """
        Semantic retrieval from the crisis knowledge base.
        Returns context, citation, and confidence score.
        The confidence score gates downstream reasoning.
        Low confidence → retrieval audit fails → retry or fallback.
        """
        print(f"[RAG] Retrieving context for: '{query[:80]}...'")
        result = self.retriever.query(query)

        print(f"[RAG] Confidence: {result['confidence']:.2f} "
              f"({'sufficient' if result['sufficient'] else 'INSUFFICIENT'})")
        print(f"[RAG] Citation:   {result['citation']}")

        return result

    def is_sufficient(self, retrieval: dict) -> bool:
        return retrieval.get("confidence", 0.0) >= CONFIDENCE_THRESHOLD
