"""
rag/ingest.py
Ingestion pipeline — fetches live data from USGS and CDC SVI,
chunks it, embeds it, and loads it into the ChromaDB vector store.
Run this once before the pipeline, or on a schedule to refresh.
"""

import requests
import json
from config import USGS_API_URL, CDC_SVI_URL
from rag.vector_store import get_collection


def ingest_usgs_events(min_magnitude: float = 3.0, limit: int = 50):
    """
    Fetches recent seismic events from USGS.
    Each event becomes a document in the vector store.
    """
    params = {
        "format":        "geojson",
        "minmagnitude":  min_magnitude,
        "limit":         limit,
        "orderby":       "time"
    }
    print("[INGEST] Fetching USGS seismic events...")
    response = requests.get(USGS_API_URL, params=params, timeout=15)
    data     = response.json()

    collection = get_collection()
    documents, metadatas, ids = [], [], []

    for i, feature in enumerate(data.get("features", [])):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [])

        # Each seismic event is chunked as a natural language document
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


def ingest_cdc_svi(limit: int = 50):
    """
    Fetches high-vulnerability census tracts from CDC SVI.
    Each tract becomes a document in the vector store.
    """
    params = {
        "where":             "RPL_THEMES > 0.75",
        "outFields":         "FIPS,RPL_THEMES,E_TOTPOP,LOCATION,EP_POV150",
        "f":                 "json",
        "resultRecordCount": limit
    }
    print("[INGEST] Fetching CDC SVI census tracts...")
    try:
        response = requests.get(CDC_SVI_URL, params=params, timeout=15)
        data     = response.json()
    except Exception as e:
        print(f"[INGEST] CDC SVI fetch failed: {e}")
        return

    collection = get_collection()
    documents, metadatas, ids = [], [], []

    for i, feature in enumerate(data.get("features", [])):
        attrs = feature.get("attributes", {})

        doc = (
            f"High social vulnerability census tract: {attrs.get('LOCATION', 'Unknown location')}. "
            f"FIPS: {attrs.get('FIPS')}. "
            f"Overall vulnerability percentile: {attrs.get('RPL_THEMES')}. "
            f"Population below 150% poverty: {attrs.get('EP_POV150')}%. "
            f"Total population: {attrs.get('E_TOTPOP')}. "
            f"Source: CDC Social Vulnerability Index 2020."
        )
        documents.append(doc)
        metadatas.append({
            "source":          "CDC_SVI",
            "fips":            str(attrs.get("FIPS", "")),
            "location":        str(attrs.get("LOCATION", "")),
            "vulnerability":   str(attrs.get("RPL_THEMES", ""))
        })
        ids.append(f"svi_{i}_{attrs.get('FIPS', i)}")

    if documents:
        collection.upsert(documents=documents, metadatas=metadatas, ids=ids)
        print(f"[INGEST] {len(documents)} CDC SVI tracts ingested.")


def run_full_ingest():
    ingest_usgs_events()
    ingest_cdc_svi()
    print("[INGEST] Complete. Vector store is ready.")


if __name__ == "__main__":
    run_full_ingest()
