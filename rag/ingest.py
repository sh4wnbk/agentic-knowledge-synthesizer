"""
rag/ingest.py
Ingestion pipeline — three sources:
  1. USGS Earthquake Hazards API (live seismic events)
  2. CDC SVI 2022 CSV (census tract vulnerability — local file)
  3. Policy documents (text files in data/policy_docs/)

Architecture note (per Gemini/design review):
  - ChromaDB holds TEXT-HEAVY documents: research findings,
    policy docs, regulatory guidance. These embed well.
  - USGS and SVI numeric data are handled via deterministic
    lookup in data_bridge_agent.py — not embedded here.
  - USGS events are ingested here only to provide semantic
    context about what induced seismicity looks like. The
    live deterministic query happens in data_bridge_agent.py.

CDC SVI CSV:
  https://www.atsdr.cdc.gov/placeandhealth/svi/data_documentation_download.html
  Download: SVI 2022 United States, CSV, census tract level
  Place at: data/svi_2022_us_tract.csv
"""

import os
import csv
import requests
from config import (
    USGS_API_URL, CDC_SVI_CSV, POLICY_DOCS_DIR,
    SEISMIC_MIN_MAGNITUDE, SVI_THRESHOLD
)
from rag.vector_store import get_collection


def ingest_usgs_events(limit: int = 50):
    """
    Fetches recent seismic events from USGS.
    Provides semantic context about induced seismicity patterns.
    Live deterministic lookup for citizen queries handled
    separately in data_bridge_agent.py.
    """
    params = {
        "format":       "geojson",
        "minmagnitude": SEISMIC_MIN_MAGNITUDE,
        "limit":        limit,
        "orderby":      "time"
    }
    print("[INGEST] Fetching USGS seismic events...")
    try:
        response = requests.get(USGS_API_URL, params=params, timeout=15)
        data     = response.json()
    except Exception as e:
        print(f"[INGEST] USGS fetch failed: {e}")
        return

    collection = get_collection()
    documents, metadatas, ids = [], [], []

    for i, feature in enumerate(data.get("features", [])):
        props  = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [])

        doc = (
            f"Seismic event: Magnitude {props.get('mag')} "
            f"{props.get('type', 'earthquake')} near {props.get('place')}. "
            f"Depth: {coords[2] if len(coords) > 2 else 'unknown'} km. "
            f"Status: {props.get('status')}. "
            f"Significance: {props.get('sig')}. "
            f"Source: USGS Earthquake Hazards Program."
        )
        documents.append(doc)
        metadatas.append({
            "source":    "USGS",
            "magnitude": str(props.get("mag", "")),
            "place":     str(props.get("place", "")),
            "time":      str(props.get("time", ""))
        })
        ids.append(f"usgs_{i}_{props.get('time', i)}")

    if documents:
        collection.upsert(documents=documents, metadatas=metadatas, ids=ids)
        print(f"[INGEST] {len(documents)} USGS events ingested.")


def ingest_cdc_svi(limit: int = 500):
    """
    Reads CDC SVI 2022 tract data from local CSV.
    Filters to high-vulnerability tracts (RPL_THEMES > 0.75).
    Threshold citation: Blackman (2025).
    """
    if not os.path.exists(CDC_SVI_CSV):
        print(
            f"[INGEST] CDC SVI CSV not found at: {CDC_SVI_CSV}\n"
            f"[INGEST] Download: https://www.atsdr.cdc.gov/placeandhealth/svi/data_documentation_download.html\n"
            f"[INGEST] Select: SVI 2022 United States, CSV, census tract level\n"
            f"[INGEST] Rename to: svi_2022_us_tract.csv → place in data/\n"
            f"[INGEST] Skipping SVI ingestion."
        )
        return

    print("[INGEST] Reading CDC SVI 2022 CSV...")
    collection = get_collection()
    documents, metadatas, ids = [], [], []
    count = 0

    with open(CDC_SVI_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if count >= limit:
                break
            try:
                rpl = float(row.get("RPL_THEMES", -1))
            except (ValueError, TypeError):
                continue
            if rpl <= SVI_THRESHOLD:
                continue

            location = row.get("LOCATION") or row.get("COUNTY") or "Unknown"
            fips     = row.get("FIPS") or row.get("STCNTY") or ""
            pop      = row.get("E_TOTPOP", "unknown")
            pov      = row.get("EP_POV150") or row.get("EP_POV", "unknown")

            doc = (
                f"High social vulnerability census tract: {location}. "
                f"FIPS: {fips}. "
                f"Overall vulnerability percentile: {rpl:.3f}. "
                f"Population below 150% poverty: {pov}%. "
                f"Total population: {pop}. "
                f"Source: CDC/ATSDR Social Vulnerability Index 2022."
            )
            documents.append(doc)
            metadatas.append({
                "source":        "CDC_SVI",
                "fips":          str(fips),
                "location":      str(location),
                "vulnerability": str(rpl)
            })
            ids.append(f"svi_{fips}_{i}")
            count += 1

    if documents:
        collection.upsert(documents=documents, metadatas=metadatas, ids=ids)
        print(f"[INGEST] {len(documents)} CDC SVI 2022 tracts ingested.")
    else:
        print("[INGEST] No high-vulnerability tracts found.")


def ingest_policy_documents():
    """
    Ingests text-heavy policy and research documents from
    data/policy_docs/ into ChromaDB.

    These are the documents that should be in the vector store —
    linguistic, policy-rich, semantically embeddable:
      - Blackman (2025) research findings
      - NIFOG 2.02 summary
      - FEMA NIMS guidance
      - ODNR TLS monitoring protocol
      - Oklahoma Corporation Commission plug-back regulations

    Each document is chunked into paragraphs for retrieval.
    """
    if not os.path.exists(POLICY_DOCS_DIR):
        print(f"[INGEST] Policy docs directory not found: {POLICY_DOCS_DIR}")
        return

    txt_files = [
        f for f in os.listdir(POLICY_DOCS_DIR)
        if f.endswith(".txt")
    ]

    if not txt_files:
        print(f"[INGEST] No .txt files found in {POLICY_DOCS_DIR}")
        return

    collection = get_collection()
    total = 0

    for filename in txt_files:
        filepath = os.path.join(POLICY_DOCS_DIR, filename)
        source   = filename.replace(".txt", "").replace("_", " ")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Chunk by paragraph — preserves semantic coherence
        paragraphs = [
            p.strip() for p in content.split("\n\n")
            if len(p.strip()) > 80
        ]

        documents, metadatas, ids = [], [], []
        for i, para in enumerate(paragraphs):
            documents.append(para)
            metadatas.append({
                "source":   "POLICY",
                "document": source,
                "filename": filename
            })
            ids.append(f"policy_{filename}_{i}")

        if documents:
            collection.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            total += len(documents)
            print(f"[INGEST] {len(documents)} chunks from {filename}")

    print(f"[INGEST] {total} policy document chunks ingested.")


def run_full_ingest():
    ingest_policy_documents()   # Policy docs first — highest semantic value
    ingest_usgs_events()        # Seismic context
    ingest_cdc_svi()            # Vulnerability tracts
    print("[INGEST] Complete. Vector store is ready.")


if __name__ == "__main__":
    run_full_ingest()
