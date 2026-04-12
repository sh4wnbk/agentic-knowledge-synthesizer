# watsonx Orchestrate Tool Registration Guide

Use this guide to register the first two tools for a working migration slice.

## Base URL

Set this to your running skill bridge URL.

- Local: `http://127.0.0.1:8080`
- Hosted: `https://YOUR_HOST`

## Tool 1: Intent Route

- Name: `intent_route`
- Method: `POST`
- URL: `{{BASE_URL}}/skills/intent-route`
- Request JSON:

```json
{
  "raw_input": "Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."
}
```

- Expected response shape:

```json
{
  "intent": {
    "raw_input": "...",
    "location": "...",
    "state": "Ohio",
    "crisis_type": "induced_seismicity",
    "is_complete": true,
    "regulatory_agency": "Ohio Department of Natural Resources (ODNR)"
  },
  "cluster": "reasoning_ohio",
  "query": "...",
  "bbox": {
    "minlatitude": 38.4,
    "maxlatitude": 41.98,
    "minlongitude": -84.82,
    "maxlongitude": -80.52
  }
}
```

## Tool 2: Crisis Brief (End-to-End)

- Name: `crisis_brief`
- Method: `POST`
- URL: `{{BASE_URL}}/workflow/crisis-brief`
- Request JSON:

```json
{
  "raw_input": "Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."
}
```

- Expected response shape:

```json
{
  "state": "confirmed_delivery",
  "content": "...",
  "citation": "...",
  "confidence": 0.0,
  "citation_score": 0.0,
  "audit_log": []
}
```

## Optional Tool 3: Governance Check

- Name: `pre_delivery_check`
- Method: `POST`
- URL: `{{BASE_URL}}/skills/governance/pre-delivery`
- Request JSON:

```json
{
  "output": "Generated response text",
  "citation": "Blackman (2025) — Mapping Disparate Risk"
}
```

## Local Verification Commands

```bash
curl -sS http://127.0.0.1:8080/health
```

```bash
curl -sS -X POST http://127.0.0.1:8080/skills/intent-route \
  -H 'Content-Type: application/json' \
  -d '{"raw_input":"Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."}'
```

```bash
curl -sS -X POST http://127.0.0.1:8080/workflow/crisis-brief \
  -H 'Content-Type: application/json' \
  -d '{"raw_input":"Emergency Log: Tremors reported near a disposal well in Youngstown, OH. SVI tract identification required."}'
```
