# AEGIS — Project Explainer

**Full name:** Agentic Emergency Geospatial Intelligence Synthesizer  
**Built by:** Shawn Blackman, Lehman College (CUNY), Environmental Science  
**Program:** IBM SkillsBuild AI Experiential Learning Lab 2026

---

## What problem does this solve?

When an earthquake hits near an injection well in Ohio or Oklahoma, a 911 dispatcher gets flooded with calls. They need three things immediately:

1. Was there an actual earthquake — how strong, how deep, where exactly?
2. Who in the affected area is most at risk — elderly residents, low-income households, people on home oxygen or ventilators?
3. Which state agency do they call first, and which federal agencies follow?

Right now, answering those three questions means opening multiple browser tabs, cross-referencing government databases by hand, and making judgment calls under pressure. Every minute of delay matters.

AEGIS answers all three questions automatically. A dispatcher types an incident report into IBM watsonx Orchestrate. The system pulls live earthquake data, census vulnerability scores, electricity-dependent resident counts, and hazardous facility locations — fuses them together — runs the result through safety checks — and returns a ready-to-use agency routing brief in under 30 seconds.

---

## Who is it for?

An Emergency Operations Center (EOC) supervisor. Not the 911 caller. Not the public. The trained professional managing the response — the person who needs to know which agencies to call, in what order, and why.

---

## What does the output look like?

Every response has exactly three sections:

**[HAZARD STATUS]**  
The confirmed earthquake magnitude, depth, and location from USGS. If the nearest USGS event is far from the reported location, the brief says so explicitly — it will not pretend a distant earthquake confirms the dispatcher's report. If hazardous industrial facilities are nearby, that is flagged here too.

**[DEMOGRAPHIC RISK (SVI)]**  
The social vulnerability score for the affected census tract, sourced from the CDC. The higher the score, the more the community depends on outside help to recover. Also includes how many residents in the county depend on electricity for medical equipment — ventilators, oxygen machines — who need priority evacuation if power goes out.

**[INTER-AGENCY ROUTING]**  
A table showing every agency the dispatcher needs to contact, grouped by urgency. Tier 1 is immediate. Tier 2 is within the hour. Tier 3 is as needed. If hazardous facilities are detected near the incident, the state environmental agency moves to Tier 1 automatically.

---

## How it works — plain version

```
Dispatcher types an incident report
        ↓
Step 1 — Read the input
  What crisis? What location? What state?
  If the input is too vague to act on → stop and ask for more detail
        ↓
Step 2 — Choose the right strategy
  Ohio earthquake → route to Ohio agencies (ODNR leads)
  Oklahoma earthquake → route to Oklahoma agencies (OCC leads)
  Assign the correct agency names so the system cannot mix them up
        ↓
Step 3 — Search the knowledge base
  Find the most relevant policy and research documents
  If the search result is too uncertain → stop rather than guess
        ↓
Step 4 — Fetch live data
  USGS: Is there a confirmed earthquake? How far from the reported location?
  Census: Which census tract is this? How vulnerable is it?
  CDC SVI: What is the vulnerability score for that tract?
  HHS: How many electricity-dependent residents are in that county?
  EPA: Are there hazardous industrial facilities near the incident?
        ↓
Step 5 — Write four draft briefs
  The IBM Granite language model writes four versions at slightly different
  settings, producing meaningfully different candidates
        ↓
Step 6 — Pick the best one and check it
  The Overseer scores each draft against the source material
  The draft that best reflects what was actually retrieved wins
  If no draft passes the quality threshold → retry, or fall back honestly
        ↓
Step 7 — Build the routing table and add verification links
  The agency table is built directly from the data, not from the language model
  This guarantees all agencies appear and no rows are missing
        ↓
Deliver the brief
```

---

## The three possible outcomes

The system always ends in one of three states. There is no fourth option.

| Outcome | What it means |
|---|---|
| **CONFIRMED DELIVERY** | All checks passed on the first attempt |
| **RETRY-CORRECTED DELIVERY** | A check failed but the system recovered within two retries |
| **HONEST FALLBACK** | The system could not produce a validated brief — it says so clearly and returns what it does know |

The honest fallback is a feature, not a bug. A system that admits uncertainty is safer for emergency use than one that produces a confident-sounding wrong answer.

---

## The six agents

### Agent 1 — Intake
Reads the raw text and pulls out three things: what kind of emergency, which state, and what location. If it cannot find all three, the pipeline stops immediately rather than proceeding on incomplete information.

### Agent 2 — Orchestrator
Decides the routing strategy. Ohio and Oklahoma use different geological reasoning — Ohio events are linked to proximity to specific wells, Oklahoma events involve basin-wide pressure dynamics. The Orchestrator selects the right approach and assigns the correct regulatory agency by name so the language model cannot confuse them.

### Agent 3 — Knowledge Retrieval
Searches a local database of policy documents, regulatory protocols, and research findings. The database holds 586 entries covering ODNR, OCC, FEMA, and state emergency management procedures. Retrieval happens before any language model generates anything — the evidence comes first.

### Agent 4 — Data Bridge
Makes the live API calls and loads local data snapshots. Six data sources:
- USGS Earthquake Hazards API — live seismic events
- U.S. Census Bureau Geocoder — converts location name to census tract
- CDC Social Vulnerability Index — vulnerability score for that tract
- HHS emPOWER — electricity-dependent residents by county (Ohio/Oklahoma snapshot)
- EPA Toxic Release Inventory — hazardous industrial facilities near the incident
- FEMA and IFRC — verification links

Also calculates how far the nearest USGS event is from the reported location. If it is more than 50 km away, the brief explicitly tells the dispatcher that the reported location has no verified seismic activity on record — which could mean the data is still being processed or the reported address needs correction.

### Agent 5 — Overseer
Runs three quality checks:
1. Before anything starts — is the input complete enough to act on?
2. After the knowledge search — was the retrieval confident enough?
3. After the language model writes its drafts — does the output actually reflect the source material?

The Overseer does not generate anything. It only evaluates and decides whether to pass, retry, or refuse.

### Agent 6 — Synthesis
Calls the IBM Granite 3-8B language model four times, each time with a slightly different randomness setting, producing four different draft briefs. The Overseer then scores each one and selects the draft most grounded in the retrieved evidence — not the one that sounds the most fluent.

---

## Why the routing table is not written by the language model

Early versions of AEGIS asked the language model to produce the agency routing table. The model regularly truncated the table, dropping agencies without explanation. Since this table is the primary operational output — the dispatcher acts on it directly — partial tables are a safety problem.

The current design generates the routing table programmatically from the bridge data after the language model is done. The language model produces the hazard summary and vulnerability assessment. The routing table is built from structured data. Every agency appears every time.

---

## The safety checks in numbers

| Check | Threshold | What fails |
|---|---|---|
| Input completeness | location + crisis type both present | Vague or incomplete reports |
| Retrieval confidence | 0.45 minimum | Weak knowledge base match |
| Citation alignment | 0.55 minimum | Draft not grounded in source material |
| Unfilled template detection | any signal | Language model returned prompt scaffolding |
| Required sections | all three present | Missing [HAZARD STATUS], [DEMOGRAPHIC RISK], or [INTER-AGENCY ROUTING] |

---

## The data sources

| Source | What it provides | How it is accessed |
|---|---|---|
| USGS Earthquake Hazards API | Live seismic events | Live API call per request |
| U.S. Census Bureau Geocoder | Address → census tract | Live API call per request |
| CDC Social Vulnerability Index 2022 | Vulnerability scores for 72,837 census tracts | Local CSV (61MB) |
| HHS emPOWER | Electricity-dependent residents by county | Local snapshot · 165 OH/OK counties |
| EPA Toxic Release Inventory | Hazardous industrial facilities | Local snapshot · 3,463 OH/OK facilities |
| FEMA · IFRC | Disaster declaration and emergency portals | Verification links only |
| ChromaDB knowledge base | Policy docs · regulatory protocols · SVI context | Local vector database |
| IBM Granite 3-8B-instruct | Language generation | IBM watsonx.ai API |

---

## The Orchestrate integration

IBM watsonx Orchestrate is the front-end the dispatcher uses. It connects to AEGIS through a single registered tool: `run_full_crisis_workflow`. The dispatcher types an incident report, Orchestrate calls that tool once, and the brief comes back.

There is deliberately only one tool. Earlier versions had four separate tools for each pipeline step, which caused the agent to loop through them trying to chain them manually — producing 22-step traces for what should be a single call. Collapsing to one tool eliminated that problem entirely.

---

## What is not yet implemented

- **Real-time emPOWER and TRI data** — both use local snapshots fetched at project time rather than live API calls. The data is accurate for the counties and facilities covered but is not updated in real time.
- **Persistent deployment** — the bridge server runs locally, exposed through an ngrok tunnel. A production deployment would require a cloud-hosted server so the tool is available without the local machine being on.
- **Citation alignment calibration for production** — the current threshold (0.55) is set for the local embedding model and Ohio/Oklahoma-weighted knowledge base. A production deployment with IBM's embedding models would use a higher threshold.

---

*Built on: IBM Granite 3-8B-instruct · IBM watsonx Orchestrate · ChromaDB · USGS Earthquake Hazards API · CDC SVI 2022 · U.S. Census Geocoder · HHS emPOWER · EPA TRI · sentence-transformers/all-MiniLM-L6-v2 · FastAPI*
