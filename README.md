# AEGIS: Agentic Emergency Geospatial Intelligence Synthesizer

**Author: Shawn Blackman** | B.S. Environmental Science, Lehman College (CUNY)

**[Live Prototype](https://aegis-synthesizer.web.app/)**: deployed on GCP Cloud Run

---

## The Problem

When a spatially predictable seismic crisis, driven by disposal-well volume and pressure dynamics, strikes a high-vulnerability community, the emergency response chain breaks at the coordination layer. The problem is not the absence of available data. It is that USGS seismic records, CDC census vulnerability scores, HHS electricity-dependent resident counts, EPA hazmat facility registries, and state regulatory contacts exist in separate systems that do not communicate under pressure.

Manual cross-referencing. Disconnected APIs. Cognitive overload.

![The Survival Gap](assets/slide_w4_01_survival_gap.png)

> *The system was designed for agency independence. The crisis requires interdependence.*

---

## The Solution

**AEGIS** is a six-agent AI pipeline that acts as an invisible coordinator for Emergency Operations Center dispatchers managing induced seismicity events. A dispatcher submits a free-text incident report. AEGIS fuses live and bundled federal data, runs the output through three governance checkpoints, and returns a validated inter-agency routing brief in under 30 seconds.

The brief contains exactly three sections, always:

- **[HAZARD STATUS]**: confirmed USGS magnitude, depth, location, distance verification, and EPA TRI compound hazmat risk
- **[DEMOGRAPHIC RISK (SVI)]**: CDC Social Vulnerability Index percentile, HHS emPOWER electricity-dependent resident count, census tract identification
- **[INTER-AGENCY ROUTING]**: tiered agency table (Tier 1 immediate, Tier 2 within the hour, Tier 3 as warranted), with EPA environmental agency promoted to Tier 1 if hazmat facilities are detected

---

## Pipeline Architecture

```mermaid
flowchart TD
    A([Dispatcher Incident Report]) --> B

    subgraph Pipeline["Six-Agent Pipeline"]
        B[Agent 1: IntakeAgent\nParse location · crisis type · state]
        B --> H1

        H1{Overseer Hook 1\nInput Audit}
        H1 -->|fail| F1([HONEST FALLBACK\nIncomplete intent])
        H1 -->|pass| C

        C[Agent 2: OrchestratorAgent\nRoute to cluster · assign regulatory agency\nBuild RAG query · set geographic bbox]
        C --> D

        D[Agent 3: RAGKnowledgeAgent\nChromaDB semantic retrieval\n586 chunks · all-MiniLM-L6-v2]
        D --> H2

        H2{Overseer Hook 2\nRetrieval Audit\nconfidence ≥ 0.45}
        H2 -->|fail| F2([HONEST FALLBACK\nLow retrieval confidence])
        H2 -->|pass| E

        E[Agent 4: DataBridgeAgent\nUSGS live · Census geocoder\nCDC SVI · HHS emPOWER · EPA TRI\nGeographic distance verification\nEPA tier promotion if hazmat detected]
        E --> G

        G[Agent 6: SynthesisAgent\nLLM provider · configurable\n4 beam candidates at varying temperature]
        G --> H3

        H3{Overseer Hook 3\nPre-Delivery Check\ncitation alignment ≥ 0.55}
        H3 -->|all fail| RB{Retry budget\nexhausted?}
        RB -->|no| D
        RB -->|yes| F3([HONEST FALLBACK\nRetry budget exhausted])
        H3 -->|best beam passes| INJ

        INJ[Deterministic post-processing\nReplace routing section with\ncomplete agency table from bridge data\nAppend verification links]
    end

    INJ --> OUT
    OUT{First pass?}
    OUT -->|yes| CD([CONFIRMED DELIVERY])
    OUT -->|no| RCD([RETRY-CORRECTED DELIVERY])
```

---

## Data Sources

```mermaid
graph LR
    subgraph Live["Live APIs"]
        USGS["USGS Earthquake\nHazards API"]
        GEO["U.S. Census\nBureau Geocoder"]
        FEMA["FEMA Disaster\nDeclarations Portal"]
        IFRC["IFRC GO\nEmergencies Portal"]
    end

    subgraph Snapshot["Local Snapshots: OH/OK"]
        SVI["CDC SVI 2022\n61MB CSV · 72,837 tracts"]
        EMP["HHS emPOWER\n165 county records"]
        TRI["EPA TRI Facilities\n3,463 active sites"]
    end

    subgraph KB["Knowledge Base: ChromaDB"]
        POL["Policy docs · 47 chunks\nODNR · OCC · FEMA · ODEQ · Ohio EPA"]
        SVI2["CDC SVI high-vulnerability\n500 tract descriptions"]
        USGS2["USGS seismic context\n50 event records"]
    end

    subgraph LLM["LLM Provider: configurable"]
        PROV["OpenAI-compatible · Anthropic · watsonx\nBeam synthesis via providers/ abstraction"]
    end

    USGS --> DataBridge
    GEO --> DataBridge
    SVI --> DataBridge
    EMP --> DataBridge
    TRI --> DataBridge
    FEMA --> DataBridge
    IFRC --> DataBridge

    KB --> RAG
    PROV --> Synthesis

    DataBridge["DataBridgeAgent\nAgent 4"]
    RAG["RAGKnowledgeAgent\nAgent 3"]
    Synthesis["SynthesisAgent\nAgent 6"]
```

---

## The Three Output States

![Trust Output Matrix](assets/slide_w5_03_trust_output_matrix.png)

| State | Condition | Trust Signal |
|---|---|---|
| CONFIRMED DELIVERY | All three hooks passed on first attempt | Full governance validation |
| RETRY-CORRECTED DELIVERY | Failed at least one hook; passed within retry budget (max 2) | System self-corrected |
| HONEST FALLBACK | Retry budget exhausted | System reported its limit honestly |

> *A system that cannot say "I don't know" gives less weight to the times it says "I know."*

---

## Key Design Decisions

### 1. Retrieval Before Reasoning
The RAGKnowledgeAgent retrieves policy context and vulnerability data **before** the Orchestrator reasons about agency routing. The knowledge base constrains the reasoning. An agent that reasons first confirms its own assumptions. In an emergency context, confident-wrong is the worst failure mode.

### 2. Beam Search Over Greedy Decoding
The SynthesisAgent generates `BEAM_WIDTH=4` candidate responses at temperatures 0.30, 0.45, 0.60, 0.75. The Overseer selects the candidate with the highest **citation alignment score**: semantic cosine similarity between the output and the retrieved source context, not the highest token probability.

### 3. Deterministic Routing Table
The `[INTER-AGENCY ROUTING]` section is not LLM-generated. After the Overseer scores and selects the best beam, `pipeline.py` replaces the routing section with a table built directly from bridge data. This guarantees all agencies appear, tiers are correct, and EPA tier promotion under compound hazmat conditions is always reflected.

### 4. Geographic Distance Verification
The DataBridgeAgent calculates the haversine distance between the reported incident location and the nearest USGS catalogued event. Three response tiers:
- **< 30 km**: Co-located: event confirmed near reported location
- **30–50 km**: Nearest regional event: moderate proximity
- **> 50 km**: No USGS-verified seismic activity at reported location; notes possible catalogue lag (5–15 min) or location correction needed

### 5. EPA Tier Promotion
If EPA TRI-listed hazmat facilities are detected within ±0.25° of the reported incident, the environmental agency (Ohio EPA or ODEQ) is automatically promoted from Tier 2 to Tier 1 in the routing matrix, with a ⚠ COMPOUND HAZMAT RISK warning prepended to its role. This is evidence-driven conditional routing: bridge data changes the governance output.

### 6. Proactive Three-Hook Governance

![Overseer Agent Three Hooks](assets/slide_w5_05_overseer_governance.png)

- **Input Audit**: catches structuring failures before reasoning begins
- **Retrieval Audit**: low-confidence retrieval does not proceed to synthesis
- **Pre-Delivery Check**: semantic citation alignment scored across all beam candidates; unfilled template detection; required section structure enforcement

---

## Core Components

| Component | Role |
|---|---|
| LLM provider layer (`providers/`) | SynthesisAgent beam generation. Configurable and auto-detecting: OpenAI-compatible endpoints (OpenAI, Groq, Together, OpenRouter, vLLM, Ollama, LM Studio), Anthropic, or IBM watsonx. Default model `gpt-4o-mini` per `config.py`. |
| Overseer moderation (`agents/overseer_agent.py`) | Heuristic input and retrieval screening. IBM Granite Guardian is an optional integration (`USE_GRANITE_GUARDIAN`, disabled by default). |
| Local audit log (`governance/audit_log.py`) | Records every Overseer hook decision with timestamp, result, and reason. |
| Firebase Hosting + GCP Cloud Run | Front end (`orchestrate/dashboard.html`) and API hosting (`orchestrate/skill_server.py`). |

The provider abstraction means `SynthesisAgent` asks for text and gets text; it does not know or care which model answered. `get_provider()` resolves from `LLM_PROVIDER`, or auto-detects from whichever credentials are present.

---

## API

The service exposes the pipeline as a single HTTP endpoint. See `orchestrate/skill_bridge_openapi.yaml` for the full OpenAPI spec.

```
POST /workflow/incident-report   → run the full pipeline, return a governed routing brief
GET  /health                     → service health check
```

The request carries the dispatcher's raw incident text; the response is one of three output states (CONFIRMED DELIVERY, RETRY-CORRECTED DELIVERY, HONEST FALLBACK) with the brief, citation alignment, retrieval confidence, and the Overseer audit log.

---

## Project Structure

```
agentic-knowledge-synthesizer/
├── pipeline.py                    # Six-agent orchestration + post-processing
├── config.py                      # All constants and thresholds
├── main.py                        # CLI validation run
├── requirements.txt
│
├── agents/
│   ├── intake_agent.py            # Agent 1: intent parsing · location resolution
│   ├── orchestrator_agent.py      # Agent 2: cluster routing · agency assignment
│   ├── rag_knowledge_agent.py     # Agent 3: ChromaDB semantic retrieval
│   ├── data_bridge_agent.py       # Agent 4: USGS · SVI · emPOWER · TRI · distance
│   ├── overseer_agent.py          # Agent 5: three-hook governance · moderation
│   └── synthesis_agent.py         # Agent 6: LLM beam generation (configurable provider)
│
├── providers/                     # LLM provider abstraction
│   ├── base.py                    # Provider interface
│   ├── openai_compat.py           # OpenAI-compatible endpoints
│   ├── anthropic.py               # Anthropic
│   └── watsonx.py                 # IBM watsonx (optional)
│
├── rag/
│   ├── ingest.py                  # Knowledge base ingestion (run once)
│   ├── vector_store.py            # ChromaDB client
│   └── retriever.py               # Semantic search + confidence scoring
│
├── governance/
│   ├── output_states.py           # OutputState enum · AgentOutput dataclass
│   └── audit_log.py               # Overseer decision logging
│
├── orchestrate/
│   ├── skill_server.py            # FastAPI service · /workflow/incident-report
│   ├── dashboard.html             # Live UI (served at /)
│   └── skill_bridge_openapi.yaml  # OpenAPI spec for the crisis-workflow API
│
├── data/
│   ├── svi_2022_us_tract.csv      # CDC SVI 2022 (61MB · committed)
│   ├── empower_oh_ok.json         # HHS emPOWER OH/OK snapshot (165 counties)
│   ├── tri_facilities_oh_ok.json  # EPA TRI OH/OK snapshot (3,463 facilities)
│   └── policy_docs/
│       ├── blackman_2025_full.txt
│       ├── nifog_2025_summary.txt
│       └── agency_response_operations.txt  # ODNR · OCC · FEMA operational protocols
│
└── tests/
    └── test_units.py              # 46 pure unit tests · no network · no LLM
```

---

## Setup

### Prerequisites
- Python 3.11+
- [uv](https://github.com/astral-sh/uv): fast Python package manager
- Credentials for one LLM provider (an OpenAI-compatible endpoint, Anthropic, or watsonx)

### Install

Install CPU-only torch **before** `requirements.txt`, or `sentence-transformers` pulls the CUDA-bundled wheel (~3 GB of `nvidia-*` packages):

```bash
cd ~/src
git clone https://github.com/sh4wnbk/agentic-knowledge-synthesizer.git
cd agentic-knowledge-synthesizer
uv venv aegis
source aegis/bin/activate
uv pip install torch --index-url https://download.pytorch.org/whl/cpu
uv pip install -r requirements.txt
```

### Credentials

```bash
cp .env.example .env
# Fill in credentials for your chosen provider, e.g. LLM_API_KEY / LLM_BASE_URL / LLM_MODEL,
# or ANTHROPIC_API_KEY. Leave LLM_PROVIDER blank to auto-detect from whichever keys are set.
```

### Seed the knowledge base (run once)

```bash
python -m rag.ingest
```

### Run

```bash
python main.py                                 # CLI validation run
uvicorn orchestrate.skill_server:app --reload  # the service Cloud Run runs
```

### Run unit tests

```bash
pytest tests/test_units.py -v
# 46 tests · no network required · no LLM required
```

---

## Governance Thresholds

| Threshold | Value | Source |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | 0.45 | Calibrated for all-MiniLM-L6-v2 |
| `CITATION_ALIGN_THRESHOLD` | 0.55 | Local prototype (all-MiniLM-L6-v2 + OH/OK knowledge base) |
| `SVI_THRESHOLD` | 0.75 | Blackman (2025): top vulnerability quartile |
| `SEISMIC_MIN_MAGNITUDE` | 1.5 | Demo threshold |
| `TRI_PROXIMITY_RADIUS_DEG` | 0.25° | ≈ 25 km, tight incident bbox for hazmat |
| `BEAM_WIDTH` | 4 | Diversity vs. API cost balance |
| `MAX_RETRIES` | 2 | Retry budget before honest fallback |

---

## Known Limitations

- **Live USGS lag**: seismic events appear in the USGS catalogue 5–15 minutes after occurrence. The geographic distance note explicitly flags when no verified activity exists at the reported location.
- **SVI, emPOWER and TRI are local snapshots**: CDC SVI, HHS emPOWER and EPA TRI are bundled with the repo and read from disk, not fetched per request. Production would call live APIs on each request.
- **FEMA and IFRC are fetched live**: both are queried on every request and merged into a ranked operational picture by `governance/external_harmonization.py`. If either call fails, the merge degrades to `status: unavailable` rather than blocking the brief.
- **Citation alignment threshold**: 0.55 is calibrated for the local `all-MiniLM-L6-v2` model against the Ohio/Oklahoma-weighted knowledge base. A higher-capacity embedding model would raise this to 0.65+.

---

## Resources

- [Live Prototype](https://aegis-synthesizer.web.app/): deployed on GCP Cloud Run
- [Video Presentation](https://drive.google.com/file/d/1Xl7nQWA-gNO77lZW76bUXIq8h8cYpHNv/view?usp=share_link): full demo walkthrough
- [Presentation Slides](https://docs.google.com/presentation/d/1fHDn6w3vWFFAbAfMxkuEIsoe0jSonjt5_6lIMFWwuRE/edit?usp=sharing): annotated deck

---

## References

- FEMA (2024) 20 Years of NIMS
- CISA (2025) NIFOG v2.02
- USGS (2024) Circular 1509: Induced Seismicity Strategic Vision
- ODNR, Ohio Induced Seismicity Traffic Light System
- OCC, Oklahoma Corporation Commission Traffic Light Protocol
- CDC/ATSDR Social Vulnerability Index 2022
- HHS emPOWER Map, Electricity-Dependent Medicare Beneficiaries
- EPA Toxic Release Inventory (TRI) Program
- Blackman, S. (2025) Mapping Disparate Risk: Disposal Well-Induced Seismicity and Social Vulnerability in Ohio and Oklahoma
