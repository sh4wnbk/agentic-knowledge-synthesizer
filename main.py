"""
main.py
Entry point.
Run the ingestion pipeline first, then the agent pipeline.
"""

from rag.ingest import run_full_ingest
from rag.vector_store import collection_size
from pipeline import run_pipeline


def main():

    # ── Ingest if vector store is empty ──────────────────────
    if collection_size() == 0:
        print("[MAIN] Vector store empty. Running ingestion pipeline...")
        run_full_ingest()
    else:
        print(f"[MAIN] Vector store ready ({collection_size()} documents).")

    # ── Test input ────────────────────────────────────────────
    test_input = (
        "There was shaking near my house on Maple Street in Youngstown. "
        "I think it was an earthquake near the disposal well. "
        "I need help. My building has cracks."
    )

    result = run_pipeline(test_input)
    result.display()

    # ── Export audit log ──────────────────────────────────────
    from agents.overseer_agent import OverseerAgent
    # Audit log is embedded in result — export separately if needed
    print("[MAIN] Pipeline complete.")


if __name__ == "__main__":
    main()
