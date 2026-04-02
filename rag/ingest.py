"""
rag/ingest.py
Ingestion pipeline — fetches live data from USGS and reads
CDC SVI data from a local CSV file into ChromaDB.

CDC SVI CSV source (free, no authentication required):
https://www.atsdr.cdc.gov/placeandhealth/svi/data_documentation_download.html
Download: SVI 2022 United States (CSV) — tract level
Place the file at: data/svi_2022_us_tract.csv
"""

import os
import csv
import requests
from config import USGS_API_URL
from rag.vector_store import get_collection

CDC_SVI_CSV = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "svi_2022_us_tract.csv"
)

SVI_THRESHOLD = 0.75


def ingest_usgs_events(min_magnitude: float = 3.0, limit: int = 50):
    """
    Fetches recent seismic events from USGS Earthquake Hazards API.
    Each event becomes a document in the vector store.
    """
    params = {
        "format":       "geojson",
        "minmagnitude": min_magnitude,
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
    else:
        print("[INGEST] No USGS events returned.")


def ingest_cdc_svi(limit: int = 500):
    """
    Reads CDC SVI 2022 census tract data from a local CSV file.
    Filters to high-vulnerability tracts (RPL_THEMES > 0.75).
    Each tract becomes a document in the vector store.

    2022 SVI uses 2018-2022 ACS estimates — more current than 2020.

    To obtain the CSV:
    1. Go to: https://www.atsdr.cdc.gov/placeandhealth/svi/data_documentation_download.html
    2. Download: SVI 2022 United States, CSV format, census tract level
    3. Rename the file to: svi_2022_us_tract.csv
    4. Place it in the data/ directory of this project
    """
    if not os.path.exists(CDC_SVI_CSV):
        print(
            f"[INGEST] CDC SVI CSV not found at: {CDC_SVI_CSV}\n"
            f"[INGEST] Download from: https://www.atsdr.cdc.gov/placeandhealth/svi/data_documentation_download.html\n"
            f"[INGEST] Select: SVI 2022 United States, CSV, census tract level\n"
            f"[INGEST] Rename to: svi_2022_us_tract.csv\n"
            f"[INGEST] Place at: data/svi_2022_us_tract.csv\n"
            f"[INGEST] Skipping SVI ingestion."
        )
        return

    print(f"[INGEST] Reading CDC SVI 2022 CSV...")

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

            location = row.get("LOCATION") or row.get("COUNTY") or "Unknown location"
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
        print("[INGEST] No high-vulnerability tracts found in CSV. "
              "Check that RPL_THEMES column exists and contains values > 0.75.")


def run_full_ingest():
    ingest_usgs_events()
    ingest_cdc_svi()
    print("[INGEST] Complete. Vector store is ready.")


if __name__ == "__main__":
    run_full_ingest()