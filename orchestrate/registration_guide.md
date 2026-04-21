# watsonx Orchestrate — Registration & Evaluation Guide

## Tool Registration

AEGIS exposes a single tool to Orchestrate. Import `skill_bridge_openapi.yaml` via
**Toolset → Add tool → Import from file**.

| Field | Value |
|---|---|
| operationId | `run_full_crisis_workflow` |
| Endpoint | `POST /workflow/incident-report` |
| Auth | None (ngrok public tunnel) |

The `start_bridge.py` script patches the `servers.url` in the YAML with the live
ngrok tunnel URL automatically on each startup.

---

## Agent Configuration

**Name:** AEGIS EOC Intelligence

**Description:**
Emergency Operations Center intelligence assistant. Analyzes seismic incident reports
and returns a validated inter-agency routing brief with live USGS data, CDC Social
Vulnerability Index, HHS emPOWER, and EPA TRI hazmat assessment.

**Behavior prompt:**
```
You are the AEGIS intelligence routing assistant for an Emergency Operations Center (EOC).
Your user is an emergency manager or dispatcher managing a live incident.

When the user provides an incident description — any report of seismic activity,
earthquake, ground shaking, or induced seismicity — call the run_full_crisis_workflow
tool immediately with the user's text as raw_input. Do not ask clarifying questions.
Do not summarize or paraphrase before calling the tool.

Return the brief exactly as received from the tool. Do not reformat, condense, or add
commentary. Present the three sections — [HAZARD STATUS], [DEMOGRAPHIC RISK (SVI)],
and [INTER-AGENCY ROUTING] — in full, followed by the verification links, status,
and citation alignment score.

If the output_status is HONEST FALLBACK, present the brief content as-is and note
that governance validation did not confirm the output.
```

**Guidelines (add as separate entries):**

| Name | Condition | Action | Tool |
|---|---|---|---|
| Incident tool invocation | User submits a message describing seismic activity, earthquake, ground shaking, tremors, or induced seismicity | Call run_full_crisis_workflow immediately with the user's full message as raw_input. Do not ask clarifying questions. One tool call per incident. | run_full_crisis_workflow |
| Incident ID handling | When calling run_full_crisis_workflow | Do not populate the incident_id parameter. Leave it empty. The server assigns a UUID automatically. | run_full_crisis_workflow |
| Raw input fidelity | When calling run_full_crisis_workflow | Pass the user's full incident text verbatim as raw_input. Do not summarize, paraphrase, or shorten it. | run_full_crisis_workflow |
| Output presentation | After receiving a response from run_full_crisis_workflow | Return the brief exactly as received from the tool. Do not reformat, condense, or add commentary. Present all three sections in full. | — |

**Quick-start prompts:**
```
M3.1 earthquake reported near Cushing, Oklahoma. Multiple calls reporting structure damage and gas odors.
```
```
Seismic event reported in Youngstown, Ohio. Residents reporting shaking and cracked foundations in Mahoning County.
```
```
Ground shaking near Pawnee, Oklahoma. M2.8 event. Possible induced seismicity near disposal well operations.
```
```
M2.9 tremor reported in Niles, Ohio. Trumbull County emergency management requesting agency routing brief.
```

---

## Evaluation Metrics

### Valid metrics for this system

| Metric | Target | Rationale |
|---|---|---|
| Tool call precision | 1.0 | One tool, called correctly |
| Tool call recall | 1.0 | No missed calls |
| Agent routing F1 | 1.0 | Correct tool, correct parameters |
| Keyword match | Pass | Agency names and section headers present |
| Response time | < 30s | Full pipeline including LLM synthesis |

### Semantic match — excluded by design

Semantic match compares the agent's response against a fixed expected output using
embedding cosine similarity. This metric is **not valid** for AEGIS and will
consistently fail for the following reason:

AEGIS returns live data. The USGS seismic event (magnitude, depth, location), SVI
tract score, HHS emPOWER beneficiary count, and EPA TRI facilities all reflect
current state at the time of the request. The USGS event returned for a Cushing,
Oklahoma prompt will differ between runs as the regional seismic catalog updates.
A fixed expected output cannot match a non-deterministic live-data response.

The authoritative quality signal is the **internal governance layer**, not the
Orchestrate semantic matcher:

- `input_audit` — intent completeness and moderation
- `retrieval_audit` — RAG confidence threshold (≥ 0.45)
- `pre_delivery_check` — citation alignment score (≥ 0.55) across all beams

These hooks run on every request and are recorded in the `audit_log` field of
every response. A `CONFIRMED DELIVERY` status means all three hooks passed.

---

## Local Verification

```bash
# Health check
curl -sS http://127.0.0.1:8080/health

# Full pipeline
curl -sS -X POST http://127.0.0.1:8080/workflow/incident-report \
  -H 'Content-Type: application/json' \
  -d '{"raw_input": "M3.1 earthquake reported near Cushing, Oklahoma. Multiple calls reporting structure damage and gas odors.", "channel": "api"}'
```

## Response shape

```json
{
  "incident_id": "uuid",
  "output_status": "CONFIRMED DELIVERY",
  "citation_alignment": "75.5%",
  "retrieval_confidence": "68.1%",
  "brief": "[HAZARD STATUS]\n...\n[DEMOGRAPHIC RISK (SVI)]\n...\n[INTER-AGENCY ROUTING]\n...",
  "citation": "Blackman (2025) — Mapping Disparate Risk: Induced Seismicity and Social Vulnerability [synthesizing Keranen et al. (2014); Hincks et al. (2018); Skoumal et al. (2024)]",
  "cluster": "reasoning_oklahoma",
  "agency_routing_baseline": { "...pre-promotion tiers..." },
  "citation_chain": "...",
  "audit_log": [
    {"hook": "input_audit", "passed": true, "reason": "Intent complete"},
    {"hook": "retrieval_audit", "passed": true, "reason": "Confidence 0.68 >= 0.45"},
    {"hook": "pre_delivery_check", "passed": true, "reason": "Citation alignment 0.76 >= 0.55"}
  ]
}
```

Note: `agency_routing_baseline` reflects pre-EPA-TRI-promotion tiers from the
Orchestrator. The `brief` field is the authoritative post-promotion routing output.
If TRI hazmat facilities are detected, the environmental agency (ODEQ or Ohio EPA)
is promoted Tier 2 → Tier 1 in the brief but this change is not reflected in
`agency_routing_baseline`.
