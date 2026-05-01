# AEGIS — Written Technology Statement

**IBM SkillsBuild AI Experiential Learning Lab 2026 | Government & Public Services**
**Author: Shawn Blackman | Lehman College CUNY | B.S. Environmental Science**
**Prototype: github.com/sh4wnbk/agentic-knowledge-synthesizer**

---

## IBM Tools and Their Purpose

**IBM Granite 3-8B-instruct** generates the hazard summary and vulnerability assessment. AEGIS produces four separate drafts at different settings, then selects the draft most grounded in the retrieved source material — scored by semantic similarity to the evidence, not by how confident the output sounds. A fluent-but-wrong answer is a more dangerous failure mode than uncertainty.

**IBM Granite Guardian 3-8B** runs a safety check on every dispatcher input before any reasoning begins — before any federal data is fetched, before any brief is drafted. It screens for content that should not enter a public safety pipeline and returns a binary decision at the earliest possible point.

**IBM watsonx Orchestrate** is the interface the dispatcher uses. AEGIS is registered as a single tool in Orchestrate — one call fires the entire six-agent pipeline and returns the completed brief. No multi-step interaction, no chaining. The dispatcher types a sentence; the brief returns.

**IBM watsonx.governance** logs every quality decision throughout the pipeline: which checks passed, which failed, the evidence alignment score for each draft, and which draft was selected. Every brief carries a complete, reviewable audit trail.

## How the Governance Layer Works

Three quality checks run before any output reaches the dispatcher.

First: is the input complete enough to act on? If the report does not include both a location and a crisis type, the pipeline stops — rather than proceeding on incomplete information.

Second: did the knowledge retrieval return a confident result? AEGIS searches a local database of emergency management policy and regulatory protocols before the language model generates anything. Evidence comes first; reasoning follows. If retrieval confidence falls below threshold, generation does not proceed.

Third: does the generated brief actually reflect the retrieved evidence? Each draft is scored for alignment with the source material. The highest-scoring draft is delivered. If no draft passes, the system retries — and if the retry budget is exhausted, it returns an Honest Fallback: a clear statement of what it could and could not produce, rather than a low-confidence answer presented as certain.

There are exactly three output states: Confirmed Delivery, Retry-Corrected Delivery, and Honest Fallback. No fourth option exists. The system either validates or tells the truth.

## A Key Design Decision

The agency routing table is built from structured data, not written by the language model. During development, the AI regularly dropped agencies from the routing table without explanation. Because a dispatcher acts directly on that table, a missing row is a missed call in a crisis. The routing table is now generated programmatically from hazardous facility data after the AI produces the brief. Every agency appears every time.

## What Comes Next

The current prototype uses local snapshots for EPA hazardous facility records and HHS electricity-dependent resident counts. The bridge server runs through a development tunnel rather than a persistent cloud host. In production: live API connections replace the snapshots, the server deploys to IBM Code Engine, and alignment thresholds recalibrate to IBM's production embedding models. The governance architecture requires no structural changes to scale to any earthquake-risk jurisdiction in the country.
