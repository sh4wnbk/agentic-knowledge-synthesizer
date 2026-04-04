"""
config.py
All environment variables, constants, and thresholds.
One source of truth for the entire pipeline.

Threshold citations:
    Blackman, S. (2025). Mapping Disparate Risk: Disposal Well-Induced
    Seismicity and Social Vulnerability in Oklahoma and Ohio.
    Lehman College (CUNY), B.S. Environmental Science.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── IBM Credentials ──────────────────────────────────────
WATSONX_API_KEY    = os.getenv("WATSONX_API_KEY")
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID")
WATSONX_URL        = "https://us-south.ml.cloud.ibm.com"
WATSON_STT_KEY     = os.getenv("WATSON_STT_API_KEY")
WATSON_STT_URL     = "https://api.us-south.speech-to-text.watson.cloud.ibm.com"

# ── Model ────────────────────────────────────────────────
# granite-3-8b-instruct: current production Granite model (2024–2025)
GRANITE_MODEL  = "ibm/granite-3-8b-instruct"

# ── Decoding — beam search, not greedy ──────────────────
# Greedy (top-1) is safe but systematically misses the
# most logically coherent completion when that completion
# is not the highest-probability token sequence.
# Beam search generates N candidates; the Overseer Agent
# selects by citation alignment score, not token probability.
BEAM_WIDTH     = 4      # Number of candidate responses generated
MAX_NEW_TOKENS = 400

# ── Seismic threshold ────────────────────────────────────
# M >= 3.0: the minimum magnitude used in Blackman (2025)
# to identify meaningful induced seismicity events in both
# Oklahoma and Ohio datasets. Below M 3.0, events are
# unlikely to cause structural damage or trigger emergency response.

SEISMIC_MIN_MAGNITUDE = 1.5  # Demo mode — shows live USGS data path
# SEISMIC_MIN_MAGNITUDE = 3.0    # Production — Blackman (2025) validated threshold

# ── SVI threshold ────────────────────────────────────────
# RPL_THEMES > 0.75: the top vulnerability quartile.
# Blackman (2025) demonstrated that the highest concentrations
# of M >= 3.0 earthquakes and disposal wells map directly onto
# census tracts with SVI scores of 0.75–1.00 in both states.
# This threshold defines the population bearing a disproportionate
# burden of anthropogenic seismic hazard.
SVI_THRESHOLD = 0.75

# ── Induced seismicity geography ─────────────────────────
# Oklahoma: basin-wide hazard driven by high-volume injection
# establishing hydraulic connectivity with crystalline basement.
# 584 high-intensity wells (>10,000 bbl, >1,000 psi) clustered
# beneath densest M >= 3.0 fields. (Blackman, 2025)
#
# Ohio: localized, proximity-based hazard driven by near-field
# pore pressure diffusion. 77% of M >= 3.0 earthquakes within
# 15 km of disposal wells. (Blackman, 2025)
#
# Both states: shallow earthquakes (<5 km) average focal depth
# of 3.79 km — firmly within brittle Precambrian crystalline
# basement, universally susceptible to injection pressure. (Blackman, 2025)

OHIO_DISPOSAL_RADIUS_KM     = 15    # Proximity buffer — Ohio hazard model
OKLAHOMA_INJECTION_DEPTH_KM = 5     # Basement interaction threshold

# Ohio approximate bounding box (covers Youngstown, Mahoning Valley)
OHIO_BBOX = {
    "minlatitude":  38.40,
    "maxlatitude":  41.98,
    "minlongitude": -84.82,
    "maxlongitude": -80.52
}

# Oklahoma approximate bounding box
OKLAHOMA_BBOX = {
    "minlatitude":  33.62,
    "maxlatitude":  37.00,
    "minlongitude": -103.00,
    "maxlongitude": -94.43
}

# ── Governance thresholds ────────────────────────────────
# CONFIDENCE_THRESHOLD: production target for IBM embedding models.
# Lowered to 0.45 for local prototype using all-MiniLM-L6-v2,
# which has a compressed cosine similarity range (0.40–0.65 for
# good matches). Restore to 0.70 when using IBM watsonx embeddings.
CONFIDENCE_THRESHOLD     = 0.45   # Local prototype (all-MiniLM-L6-v2)
# CONFIDENCE_THRESHOLD   = 0.70   # Production (IBM watsonx embeddings)

CITATION_ALIGN_THRESHOLD = 0.60   # Minimum citation alignment — pre-delivery
MAX_RETRIES              = 2      # Retry budget cap — Overseer loop

# ── External APIs ────────────────────────────────────────
USGS_API_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# ── ChromaDB ─────────────────────────────────────────────
CHROMA_PERSIST_DIR     = "./chroma_db"
CHROMA_COLLECTION_NAME = "crisis_knowledge_base"
EMBEDDING_MODEL        = "all-MiniLM-L6-v2"  # Local; swap for IBM embeddings in production

# ── Data paths ───────────────────────────────────────────
CDC_SVI_CSV      = os.path.join(os.path.dirname(__file__), "data", "svi_2022_us_tract.csv")
POLICY_DOCS_DIR  = os.path.join(os.path.dirname(__file__), "data", "policy_docs")
