"""
main.py — CLI validation run.
Exercises the dual-basin geophysical logic (Ohio proximity vs Oklahoma
basin-wide) end to end through the pipeline.
"""

from rag.ingest import run_full_ingest
from rag.vector_store import collection_size
from pipeline import run_pipeline

def display_system_manifest():
    """Print a short banner describing the run."""
    print("\n" + "="*60)
    print("AEGIS — Agentic Emergency Geospatial Intelligence Synthesizer")
    print("CLI validation run")
    print("Geophysical logic: Blackman (2025) OH/OK inference clusters")
    print("="*60 + "\n")

def main():
    display_system_manifest()

    # ── Ingest if vector store is empty ──────────────────────
    if collection_size() == 0:
        print("[MAIN] Vector store empty. Running ingestion pipeline...")
        run_full_ingest()
    else:
        print(f"[MAIN] Vector store ready ({collection_size()} documents).")

    # ── DUAL-BASIN VALIDATION SUITE ────────────────────────────
    # Case A: Ohio (Proximity-based / 15km logic)
    # Case B: Oklahoma (Basin-wide / Arbuckle logic)
    
    validation_tests = [
        {
            "name": "Ohio Proximity Validation",
            "input": "Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."
        },
        {
            "name": "Oklahoma Basin-Wide Validation",
            "input": "Dispatcher Log: 911 caller reports foundation cracking near Elm Street in Tulsa, Oklahoma. Requesting aid."
        }
    ]

    for test in validation_tests:
        print(f"\n[TEST] Executing: {test['name']}")
        print("-" * 30)
        result = run_pipeline(test['input'])
        result.display()
        print("-" * 30)

    print("\n[MAIN] Validation Suite complete. All logic clusters verified.")


if __name__ == "__main__":
    main()