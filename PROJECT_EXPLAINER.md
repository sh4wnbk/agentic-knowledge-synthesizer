# AEGIS — Project Explainer

**Full name:** Agentic Emergency Geospatial Intelligence Synthesizer  
**Built by:** Shawn Blackman, Lehman College (CUNY), Environmental Science  
**Program:** IBM SkillsBuild AI Experiential Learning Lab 2026  

---

## What this project is and why it exists

When an earthquake hits near an injection well in Ohio or Oklahoma, a 911 dispatcher gets a flood of calls. They need to know three things immediately:

1. Is there a confirmed seismic event, and how big is it?
2. Who in the affected area is most vulnerable — elderly, low-income, limited English?
3. Which state agency do they call, and what federal coordination do they trigger?

Right now, getting those three answers requires a dispatcher to cross-reference USGS earthquake data, CDC census vulnerability scores, and state regulatory contacts by hand, under pressure, in real time.

AEGIS does all of that automatically. A dispatcher pastes a dispatch log into IBM watsonx Orchestrate. AEGIS calls a governed six-agent Python pipeline, fuses live federal data, runs the output through three safety checks, and returns a structured agency brief in under 30 seconds.

---

## The technology stack in one paragraph

The pipeline is written in Python. It runs as a FastAPI web server locally, exposed to the internet via an ngrok tunnel. IBM watsonx Orchestrate acts as the front-end — it's the chat interface the dispatcher uses. When Orchestrate receives input, it calls the FastAPI server via a registered OpenAPI tool. The server runs six sequential agents, each doing one job. The language model used for text generation is IBM Granite 3-8B-instruct, accessed via the watsonx.ai API. Semantic memory is stored in ChromaDB, a local vector database. Real-time seismic data comes from the USGS Earthquake Hazards API. Demographic vulnerability data comes from the CDC Social Vulnerability Index 2022, a 61MB census-tract-level dataset stored locally.

---

## The file structure

```
agentic-knowledge-synthesizer/
│
├── pipeline.py              ← The main sequence. Calls all six agents in order.
├── config.py                ← Every constant and threshold in one place.
│
├── agents/                  ← One file per agent.
│   ├── intake_agent.py      ← Agent 1: reads the raw input
│   ├── orchestrator_agent.py← Agent 2: decides the routing strategy
│   ├── rag_knowledge_agent.py← Agent 3: searches the knowledge base
│   ├── data_bridge_agent.py ← Agent 4: calls external APIs
│   ├── overseer_agent.py    ← Agent 5: governance and safety checks
│   └── synthesis_agent.py  ← Agent 6: generates the final brief
│
├── rag/                     ← The knowledge base layer.
│   ├── ingest.py            ← Loads data into ChromaDB (run once)
│   ├── vector_store.py      ← Connects to ChromaDB
│   └── retriever.py         ← Runs semantic searches
│
├── governance/
│   ├── output_states.py     ← Defines the three possible outcomes
│   └── audit_log.py         ← Records every decision the Overseer makes
│
├── orchestrate/
│   ├── skill_server.py      ← The FastAPI server Orchestrate calls
│   └── skill_bridge_openapi.yaml ← Tells Orchestrate what endpoints exist
│
└── data/
    ├── svi_2022_us_tract.csv    ← CDC vulnerability data (not in git, 61MB)
    └── policy_docs/             ← Research papers and regulatory guides
        ├── blackman_2025_full.txt
        └── nifog_2025_summary.txt
```

---

## How a request flows through the system

Here is the exact sequence of events when a dispatcher sends a message:

```
Dispatcher types in Orchestrate chat
    ↓
Orchestrate calls POST /workflow/crisis-brief on the FastAPI bridge
    ↓
pipeline.run_pipeline() starts
    ↓
[Agent 1] IntakeAgent     — what is this about and where?
    ↓
[Hook 1]  OverseerAgent   — is the input complete enough to proceed?
    ↓
[Agent 2] OrchestratorAgent — which state, which agency, which search strategy?
    ↓
[Agent 3] RAGKnowledgeAgent — what does the knowledge base say about this?
    ↓
[Hook 2]  OverseerAgent   — is the retrieved knowledge confident enough?
    ↓
[Agent 4] DataBridgeAgent — what is USGS reporting? what is the SVI score?
    ↓
[Agent 5] SynthesisAgent  — generate four candidate briefs using Granite LLM
    ↓
[Hook 3]  OverseerAgent   — which candidate is most grounded in the source?
    ↓
AgentOutput returned to FastAPI → Orchestrate displays it
```

---

## The six agents, explained plainly

### Agent 1 — IntakeAgent (`agents/intake_agent.py`)

**Job:** Read the raw dispatch text and extract three things — what kind of crisis is it, which state is it in, and what is the specific location.

**How it works:** It scans the text for keywords. If it sees words like "tremor," "earthquake," "shaking," "seismic," or "quake," it classifies the crisis as `induced_seismicity`. It checks for state names and county/city names against a built-in lookup table covering major Ohio and Oklahoma locations. If it finds a street address pattern, it uses that. If it finds GPS coordinates, it uses those. If it detects a state but no specific city, it falls back to the state name so the pipeline can still proceed.

**What it produces:** A structured dictionary:
```python
{
  "raw_input":   "the original text",
  "location":    "Youngstown, OH",
  "state":       "Ohio",
  "crisis_type": "induced_seismicity",
  "is_complete": True
}
```

**What happens if it fails:** `is_complete` is False. The Overseer stops the pipeline at Hook 1 and returns an honest fallback asking for more detail. No hallucination.

---

### Agent 2 — OrchestratorAgent (`agents/orchestrator_agent.py`)

**Job:** Decide which reasoning strategy to use and which regulatory agency is responsible.

**How it works:** It maps the crisis type and state to one of five clusters:
- Ohio induced seismicity → `reasoning_ohio` cluster → ODNR (Ohio Dept. of Natural Resources)
- Oklahoma induced seismicity → `reasoning_oklahoma` cluster → OCC (Oklahoma Corporation Commission)
- Other types → `coordination` or `synthesis` cluster

It also builds a specialized search query for the knowledge base. For Ohio, the query includes technical terms like "15 km disposal well proximity," "pore pressure diffusion," and "ODNR Traffic Light System" because Ohio's hazard model is proximity-based. For Oklahoma, the query includes "basin-wide hydraulic connectivity," "Arbuckle Group injection zone," and "OCC plug-back regulations" because Oklahoma's hazard is regional, not local.

Finally it returns the geographic bounding box for the state — a set of lat/lon coordinates used to constrain the USGS query so it only returns earthquakes in that region.

**Why this matters:** Without the bounding box, a Tulsa query could return an earthquake in Chile. Without the cluster-specific query, the knowledge base search would be too generic to retrieve the right policy context.

---

### Agent 3 — RAGKnowledgeAgent (`agents/rag_knowledge_agent.py`)

**Job:** Search the knowledge base for the most relevant information before any language model generates anything.

**How it works:** It passes the query from Agent 2 into the Retriever, which converts the query into a numeric vector (an embedding) using the `all-MiniLM-L6-v2` model and finds the five most similar documents in ChromaDB using cosine similarity. It calculates a confidence score as the average similarity across those five results.

**What the knowledge base contains:**
- Blackman (2025) research paper — the scientific grounding for Ohio and Oklahoma hazard models
- CISA NIFOG v2.02 — national interoperability field operations guide
- USGS seismic event records (ingested at startup for semantic context)
- CDC SVI high-vulnerability census tract descriptions

**What it produces:**
```python
{
  "context":    "the retrieved text passages",
  "citation":   "Blackman (2025) — Mapping Disparate Risk...",
  "confidence": 0.715,
  "sufficient": True
}
```

**RAG = Retrieval-Augmented Generation.** This means the language model does not generate from memory alone. It is given retrieved evidence and told to cite it. This is the architectural decision that prevents fabrication.

---

### Agent 4 — DataBridgeAgent (`agents/data_bridge_agent.py`)

**Job:** Fetch real numbers from real federal databases. This is where live data enters the pipeline.

**It makes four calls:**

**Call 1 — USGS Earthquake Hazards API**  
URL: `https://earthquake.usgs.gov/fdsnws/event/1/query`  
Parameters: GeoJSON format, minimum magnitude from config, limited to the state bounding box from Agent 2, ordered by time, top 5 results.  
Returns: magnitude, location description, depth in km, event count.  
If nothing is found: explicitly returns `"CLEAR: NO RECENT SEISMIC EVENTS DETECTED IN REGION"` — this is intentional. An empty result is reported honestly so the language model doesn't invent an earthquake.

**Call 2 — U.S. Census Bureau Geocoder**  
URL: `https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress`  
What it does: Takes the location string (e.g., "Youngstown, OH") and resolves it to latitude/longitude coordinates, then resolves those coordinates to a census tract GEOID (a unique 11-digit identifier for each census tract in the country).  
Fallback: If the geocoder can't resolve the address, it checks a hardcoded table of city-center coordinates for known demo cities.

**Call 3 — CDC SVI 2022 CSV (local)**  
File: `data/svi_2022_us_tract.csv`  
What it does: Takes the census tract GEOID from Call 2, looks up the row in the CSV, and returns the SVI percentile scores for that tract — overall vulnerability, poverty rate, limited English percentage, older adult percentage, and four sub-theme scores.  
The CSV is loaded once and cached in memory using `lru_cache` so repeated calls don't re-read 61MB from disk.

**Call 4 — FEMA and NGO (stubs)**  
Currently returns hardcoded prototype values. In production these would call the FEMA API and Red Cross API with authenticated tokens. Marked clearly in the code as stubs.

---

### Agent 5 — OverseerAgent (`agents/overseer_agent.py`)

**Job:** Run three safety checks at three different points in the pipeline and decide whether to pass, retry, or refuse.

This is the governance layer. It does not generate anything. It only evaluates.

**Hook 1 — Input Audit**  
Runs after Agent 1.  
Checks: does the intent have both a location and a crisis type?  
If no: returns `HONEST_FALLBACK` immediately.  
Cost: nearly zero — just checks two boolean fields.

**Hook 2 — Retrieval Audit**  
Runs after Agent 3.  
Checks: is the retrieval confidence score above 0.45?  
If no: retries the retrieval up to 2 times. If still below threshold after retries: returns `HONEST_FALLBACK` with the partial citation.  
The 0.45 threshold is calibrated for the local `all-MiniLM-L6-v2` embedding model, which has a compressed similarity range compared to IBM's production embedding models.

**Hook 3 — Pre-Delivery Check**  
Runs after Agent 6 generates four candidate briefs.  
Two sequential checks:

*Check A — Unfilled template detection:*  
Scans each candidate for phrases that indicate the language model returned the prompt instructions instead of completing them — things like "1 sentence specifying," "[insert," "fill in," "placeholder." Any candidate containing these signals is rejected regardless of its alignment score.

*Check B — Semantic citation alignment:*  
Converts both the candidate output and the retrieved context into embeddings using `all-MiniLM-L6-v2` and computes cosine similarity between them. This measures whether the output is semantically grounded in what was actually retrieved — not just whether it copied the citation string.  
Threshold: 0.60. Candidates below this are rejected.  
The candidate with the highest passing score is selected as the final output.

**Why this matters:** Before this was implemented as embedding similarity, it used keyword overlap — which measured whether the output contained words from the citation string, not whether it reflected the retrieved content. Citation scores of 1.0 were routine regardless of output quality. With embedding similarity, a score of 0.687 means the output is meaningfully semantically aligned with what was retrieved. That is a real signal.

**What the Overseer logs:**  
Every hook decision — pass or fail, with timestamp, score, and reason — is recorded in an `AuditLog` object and returned with the final output. The dispatcher can see exactly what was checked and why.

---

### Agent 6 — SynthesisAgent (`agents/synthesis_agent.py`)

**Job:** Call the IBM Granite LLM four times to generate four different candidate briefs, then hand them all to the Overseer for selection.

**How it works:**  
It authenticates with IBM Cloud's IAM service to get a Bearer token (refreshed automatically before the 60-minute expiry). It sends the prompt to `ibm/granite-3-8b-instruct` via the watsonx.ai text generation API four times, each time with a slightly different temperature:
- Beam 0: temperature 0.30 (near-deterministic)
- Beam 1: temperature 0.45
- Beam 2: temperature 0.60
- Beam 3: temperature 0.75 (more varied)

Temperature controls how much randomness is in the output. Running four calls at different temperatures produces four meaningfully different candidates. The Overseer picks the one most semantically aligned with the retrieved evidence — not the one with the highest token probability.

**The prompt structure:**  
The prompt tells Granite it is an automated intelligence core for a 911 CAD system. It injects:
- The retrieved policy/research context (from Agent 3)
- The live SVI tract data (from Agent 4)
- The live USGS seismic data (from Agent 4)
- The original dispatch log
- The exact regulatory agency name (ODNR or OCC — injected by Agent 2 to prevent the model from guessing the acronym)

It enforces a strict three-section output format and prohibits any preamble, pleasantries, or invented policy codes.

**Token management:**  
IAM tokens expire after 60 minutes. The agent stores the token with its expiry timestamp and automatically re-fetches it 60 seconds before expiration. This prevents silent failures in long demo sessions.

---

## The three output states

Every pipeline run ends in exactly one of three states. There is no fourth state.

| State | Meaning |
|---|---|
| `CONFIRMED_DELIVERY` | Passed all three hooks on the first attempt |
| `RETRY_CORRECTED_DELIVERY` | Failed at least one hook, but passed within the retry budget (max 2 retries) |
| `HONEST_FALLBACK` | Could not produce a validated output — returns what it knows with a transparent explanation |

The honest fallback is a design choice, not a failure mode. A system that says "I can't answer this confidently" is safer for emergency dispatch than one that fabricates a plausible-sounding response.

---

## The RAG layer in detail (`rag/`)

**What RAG means:**  
Retrieval-Augmented Generation. Before the language model generates anything, the system retrieves relevant documents from a knowledge base and gives them to the model as context. The model is then grounded in real retrieved content rather than operating from its training data alone.

**The knowledge base (ChromaDB):**  
ChromaDB is a local vector database. Text is converted to numeric vectors (embeddings) using `all-MiniLM-L6-v2`, a 22-million-parameter sentence embedding model. Similar texts have similar vectors. Querying the database with a question returns the documents whose vectors are closest to the question's vector — semantic similarity search.

**What gets ingested (`rag/ingest.py`):**  
Run once to populate the database. Three sources, in priority order:

1. *Policy documents* — `data/policy_docs/*.txt`. Each document is split into paragraphs (chunks > 80 characters) and each paragraph is stored as a separate searchable entry. Currently: Blackman (2025) research paper and NIFOG 2.02 summary.

2. *USGS seismic events* — fetched live at ingest time. The most recent 50 events above the minimum magnitude threshold are converted to text descriptions and embedded. These provide semantic context about what induced seismicity looks like, not the real-time event data (that comes from Agent 4).

3. *CDC SVI high-vulnerability tracts* — census tracts with `RPL_THEMES > 0.75` (top quartile) are converted to text descriptions and embedded. The 0.75 threshold is from Blackman (2025).

**Confidence scoring:**  
ChromaDB returns cosine distances (0 = identical, 1 = completely different). The Retriever converts these to similarities (`1 - distance`) and averages them across the top 5 results. This average is the confidence score. A score of 0.71 means the retrieved documents are meaningfully related to the query.

---

## The data sources and API calls — complete list

| Source | Type | What it provides | Called by |
|---|---|---|---|
| USGS Earthquake Hazards API | Live REST API | Recent seismic events, magnitude, depth, location | DataBridgeAgent |
| U.S. Census Bureau Geocoder | Live REST API | Address → lat/lon → census tract GEOID | DataBridgeAgent |
| CDC SVI 2022 CSV | Local file | Census tract vulnerability scores | DataBridgeAgent |
| IBM watsonx.ai | Live REST API | Granite LLM text generation | SynthesisAgent |
| IBM Cloud IAM | Live REST API | Authentication token | SynthesisAgent |
| ChromaDB | Local database | Semantic search over policy docs | RAGKnowledgeAgent |
| FEMA API | Stub | Shelter and assistance status | DataBridgeAgent (not live) |
| NGO / Red Cross | Stub | Hotline and housing resources | DataBridgeAgent (not live) |

---

## The Orchestrate integration (`orchestrate/`)

**`skill_server.py`** is a FastAPI application that wraps the Python pipeline in HTTP endpoints. When Orchestrate calls a tool, it is calling one of these endpoints.

Two endpoints matter for the demo:

- `POST /skills/intent-route` — runs Agent 1 and Agent 2 only. Returns the structured intent, cluster name, semantic query, and bounding box. Useful for inspecting routing decisions.
- `POST /workflow/crisis-brief` — runs the full six-agent pipeline. Returns the final `AgentOutput` as JSON.

**`skill_bridge_openapi.yaml`** is the machine-readable description of those endpoints. Orchestrate reads this file to understand what tools are available, what inputs they expect, and what URL to call. The `servers` field contains the public URL of the ngrok tunnel.

**The ngrok tunnel** exposes the locally running FastAPI server to the internet. Orchestrate cannot call `localhost` — it needs a public HTTPS URL. ngrok creates an encrypted tunnel from the public URL to port 8080 on the local machine. The tunnel must be running for Orchestrate tool calls to succeed.

**Demo startup sequence:**
```bash
# Terminal 1: start the pipeline server
uvicorn orchestrate.skill_server:app --host 0.0.0.0 --port 8080

# Terminal 2: open the public tunnel
ngrok http 8080
```

---

## The governance thresholds and where they come from

| Threshold | Value | Source |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | 0.45 | Calibrated for all-MiniLM-L6-v2 similarity range |
| `CITATION_ALIGN_THRESHOLD` | 0.60 | Empirically validated on test cases |
| `SVI_THRESHOLD` | 0.75 | Blackman (2025) — top vulnerability quartile |
| `SEISMIC_MIN_MAGNITUDE` | 1.5 (demo) / 3.0 (prod) | Blackman (2025) — meaningful damage threshold |
| `OHIO_DISPOSAL_RADIUS_KM` | 15 | Blackman (2025) — 77% of M≥3.0 events within 15 km |
| `OKLAHOMA_INJECTION_DEPTH_KM` | 5 | Blackman (2025) — basement interaction depth |
| `BEAM_WIDTH` | 4 | Balances diversity vs. API cost |
| `MAX_RETRIES` | 2 | Retry budget before honest fallback |

---

## What is not implemented (honest accounting)

- **FEMA API integration** — stub returning hardcoded True. Production would require authenticated Login.gov token and FEMA NIMS API access.
- **NGO / Red Cross API** — stub. Production would call Red Cross API and municipal housing registries.
- **Legal scope verification** — `_verify_legal_scope()` always returns True. Production would validate data-sharing authorization under state law.
- **Watson Speech-to-Text** — the `transcribe()` method on IntakeAgent is not implemented. Audio input is not currently active.
- **IBM watsonx embeddings** — the pipeline uses the local `all-MiniLM-L6-v2` model. Production would swap this for IBM's embedding endpoint, raising the confidence threshold from 0.45 to 0.70.
- **Persistent deployment** — the system runs locally with an ngrok tunnel. There is no cloud deployment; the SkillsBuild account does not support it.

---

## How to run this locally

**Prerequisites:**
- Python 3.11+
- IBM Cloud account with watsonx.ai access
- `.env` file with `WATSONX_API_KEY` and `WATSONX_PROJECT_ID`
- CDC SVI CSV at `data/svi_2022_us_tract.csv` (download from CDC/ATSDR)
- ngrok installed and authenticated

**Steps:**
```bash
# Install dependencies
pip install -r requirements.txt

# Seed the knowledge base (run once)
python rag/ingest.py

# Start the FastAPI bridge
uvicorn orchestrate.skill_server:app --host 0.0.0.0 --port 8080

# In a second terminal, open the tunnel
ngrok http 8080

# Import orchestrate/skill_bridge_openapi.yaml into watsonx Orchestrate
# Update the server URL in the YAML to match your ngrok URL first
```

---

*Built on: IBM Granite 3-8B-instruct · ChromaDB · USGS Earthquake Hazards API · CDC SVI 2022 · U.S. Census Geocoder · IBM watsonx Orchestrate · FastAPI · sentence-transformers/all-MiniLM-L6-v2*
