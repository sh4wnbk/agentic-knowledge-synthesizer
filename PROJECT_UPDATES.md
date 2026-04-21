# AEGIS — Project Update Log

**Author:** Shawn Blackman, Lehman College (CUNY)  
**Program:** IBM SkillsBuild AI Experiential Learning Lab 2026

---

## Current State (April 2026)

AEGIS produces validated inter-agency routing briefs for induced seismicity events in Ohio and Oklahoma. All four canonical test cases return CONFIRMED DELIVERY with citation alignment between 63–77%.

### Validated test cases

| Incident | State | SVI | TRI Facilities | emPOWER | Citation Alignment |
|---|---|---|---|---|---|
| Youngstown, OH | Ohio | 0.9575 (HIGH) | 59 | 2,909 | ~65% |
| Niles, OH | Ohio | 0.7557 (HIGH) | 19 | 2,806 | ~69% |
| Cushing, OK | Oklahoma | 0.5417 | 1 | 708 | ~75% |
| Pawnee, OK | Oklahoma | 0.8352 (HIGH) | 10 | 273 | ~69% |

---

## What changed from the original prototype

### Data pipeline expanded

The original DataBridgeAgent made four calls: USGS, Census geocoder, CDC SVI, and a FEMA stub. It now makes six:

- **HHS emPOWER** — electricity-dependent Medicare beneficiaries by county (Ohio and Oklahoma). Loaded from a local snapshot of 165 county records. Shows how many residents on ventilators, oxygen machines, or other powered medical equipment need priority evacuation if power goes out.

- **EPA Toxic Release Inventory** — active hazardous industrial facilities within ±0.25° of the incident. Loaded from a local snapshot of 3,463 Ohio and Oklahoma facilities. If any are found, the environmental agency (Ohio EPA or ODEQ) is automatically promoted from Tier 2 to Tier 1 in the routing table.

Both data sources were intended to use live public APIs. Both API endpoints were broken or returned wrong data formats during development. The solution was to fetch the data once, store it in local JSON files, and load it at startup with a cache. The data is accurate for the covered geography.

### Geographic distance verification

The original system returned whatever USGS found without flagging whether it matched the reported location. If the nearest USGS event was 140 km from the incident, the brief presented it without comment.

The current system calculates the distance between the reported location and the nearest USGS event and responds in three tiers:
- Under 30 km: co-located, event confirmed near reported location
- 30–50 km: nearest regional event, moderate proximity
- Over 50 km: explicitly tells the dispatcher that no verified seismic activity exists at the reported location, and notes that USGS data typically lags 5–15 minutes after an event

This is operationally important. A dispatcher reporting a Youngstown earthquake should not receive a brief that silently confirms a Madison, Ohio event 79 km away.

### Routing table made deterministic

The original system asked the language model to produce the agency routing table. The model regularly truncated it, dropping agencies without explanation.

The current system asks the language model to produce the hazard summary and vulnerability assessment only. After the Overseer scores and selects the best draft, `pipeline.py` replaces the routing section with a table built directly from the bridge data. Every agency appears every time. Tier promotion under compound hazmat conditions is always reflected.

### Orchestrate integration simplified

The original Orchestrate setup registered four tools: intentRoute, bridge, crisisBrief, and callTransaction. The callTransaction endpoint was deleted but remained in the YAML, causing the ReAct agent to loop for 22 steps trying to chain tools that no longer existed.

The current setup registers one tool: `run_full_crisis_workflow` → `POST /workflow/incident-report`. One call, one response, no chaining. The evaluation now returns F1=1, precision=1, recall=1, zero missed calls, zero incorrect parameters.

### Output moderation false positives fixed

The Granite Guardian safety model was originally applied to pipeline output as well as user input. Legitimate emergency management language — HAZMAT, INFRASTRUCTURE RISK, gas leak evaluation — triggered false positives and blocked valid briefs.

The fix: Granite Guardian runs on user input and retrieved content only. Pipeline output uses heuristic-only moderation. Emergency management language is not harmful.

### Knowledge base expanded

The original knowledge base held policy documents and CDC SVI context. A third source was added: `agency_response_operations.txt`, an 11-chunk document covering the operational procedures of ODNR, OCC, FEMA, Ohio EPA, ODEQ, Ohio EMA, ODEM, and the compound hazmat escalation protocol. This improved retrieval confidence for Oklahoma queries from below threshold to 0.68–0.74.

### Oklahoma RAG query rewritten

The original Oklahoma query used statistical and geological language: Arbuckle Group, basin-wide hydraulic connectivity. The knowledge base has operational chunks describing how agencies actually respond. The query was rewritten to match: OCC plug-back notification, ODEQ hazard assessment, ODEM shelter activation. Retrieval confidence for Oklahoma queries improved and CONFIRMED DELIVERY rates stabilized.

### Citation alignment threshold lowered

The original threshold was 0.60. All-MiniLM-L6-v2 produces lower raw similarity scores than IBM's production embedding models, and the knowledge base is weighted toward Ohio and Oklahoma content. The threshold was lowered to 0.55 for this prototype. Production deployment with IBM watsonx embeddings would raise it to 0.65+.

---

## Architecture decisions that did not change

- **Three output states only.** CONFIRMED DELIVERY, RETRY-CORRECTED DELIVERY, HONEST FALLBACK. No fourth state. The system either validates or tells the truth.
- **Retrieval before reasoning.** The knowledge base is searched before the language model generates anything. Evidence constrains output.
- **Beam width 4.** Four candidates at temperatures 0.30, 0.45, 0.60, 0.75. The Overseer selects by citation alignment, not token probability.
- **Three Overseer hooks.** Input Audit, Retrieval Audit, Pre-Delivery Check. Retry budget 2. Honest Fallback when exhausted.
- **Granite 3-8B-instruct.** The synthesis model has not changed.

---

## What remains to be done

- **Persistent deployment** — the bridge runs locally via ngrok. A cloud-hosted instance would make the tool available without the local machine running.
- **Real-time emPOWER and TRI** — replace local snapshots with live API calls when stable endpoints are confirmed.
- **CAD input format testing** — real 911 dispatch logs use terse shorthand. The intake parser has not been tested against raw CAD data formats.
- **ODNR and OCC protocol documents** — the operational summary document captures the key thresholds, but ingesting the actual source PDFs from ODNR and OCC would improve RAG retrieval precision.
