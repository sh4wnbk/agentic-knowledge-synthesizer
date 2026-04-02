"""
config.py
All environment variables, constants, and thresholds.
One source of truth for the entire pipeline.
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
GRANITE_MODEL      = "ibm/granite-13b-instruct-v2"

# ── Decoding — beam search, not greedy ──────────────────
# Greedy (top-1) is safe but systematically misses the
# most logically coherent completion when that completion
# is not the highest-probability token sequence.
# Beam search generates N candidates; the Overseer Agent
# selects by citation alignment score, not token probability.
BEAM_WIDTH         = 4      # Number of candidate responses generated
MAX_NEW_TOKENS     = 400

# ── Governance thresholds ────────────────────────────────
CONFIDENCE_THRESHOLD    = 0.70   # Minimum retrieval confidence to proceed
CITATION_ALIGN_THRESHOLD = 0.60  # Minimum citation alignment to pass pre-delivery
MAX_RETRIES             = 2      # Retry budget cap — Overseer loop

# ── External APIs ────────────────────────────────────────
USGS_API_URL   = "https://earthquake.usgs.gov/fdsnws/event/1/query"
CDC_SVI_URL = "https://onemap.cdc.gov/OneMapServices/rest/services/SVI/CDC_ATSDR_Social_Vulnerability_Index_2020_USA/FeatureServer/0/query"

# ── ChromaDB ─────────────────────────────────────────────
CHROMA_PERSIST_DIR      = "./chroma_db"
CHROMA_COLLECTION_NAME  = "crisis_knowledge_base"
EMBEDDING_MODEL         = "all-MiniLM-L6-v2"   # Local; swap for IBM embeddings in production
