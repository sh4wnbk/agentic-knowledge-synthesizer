"""
rag/retriever.py
Semantic retrieval from ChromaDB.
Confidence scoring based on cosine similarity of returned documents.
This is what makes retrieval-before-reasoning architecturally honest.
"""

from rag.vector_store import get_collection
from config import CONFIDENCE_THRESHOLD


class Retriever:

    def __init__(self, n_results: int = 5):
        self.n_results = n_results
        self.collection = get_collection()

    def query(self, query_text: str) -> dict:
        """
        Semantic search against the crisis knowledge base.
        Returns documents, sources, and a confidence score.
        Confidence = mean cosine similarity of top-n results.
        ChromaDB returns distances; convert to similarity.
        """
        if self.collection.count() == 0:
            print("[RETRIEVER] Vector store is empty. Run rag/ingest.py first.")
            return self._empty_result()

        results = self.collection.query(
            query_texts=[query_text],
            n_results=min(self.n_results, self.collection.count()),
            include=["documents", "metadatas", "distances"]
        )

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        # Cosine distance → similarity (ChromaDB uses cosine distance: 0=identical)
        similarities  = [1 - d for d in distances]
        confidence    = sum(similarities) / len(similarities) if similarities else 0.0
        citation      = self._build_citation(metadatas)
        context       = "\n\n".join(documents)

        return {
            "context":    context,
            "documents":  documents,
            "metadatas":  metadatas,
            "confidence": round(confidence, 3),
            "citation":   citation,
            "sufficient": confidence >= CONFIDENCE_THRESHOLD
        }

    def _build_citation(self, metadatas: list) -> str:
        sources = set()
        for m in metadatas:
            if m.get("source") == "USGS":
                sources.add("USGS Earthquake Hazards API (real-time)")
            elif m.get("source") == "CDC_SVI":
                sources.add("CDC Social Vulnerability Index 2020")
        return " | ".join(sorted(sources)) if sources else None

    def _empty_result(self) -> dict:
        return {
            "context":    "",
            "documents":  [],
            "metadatas":  [],
            "confidence": 0.0,
            "citation":   None,
            "sufficient": False
        }
