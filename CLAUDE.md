# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

AEGIS (Agentic Emergency Geospatial Intelligence Synthesizer) takes one
plain-language incident report after an induced earthquake and returns a
validated, source-cited routing brief.

The reader is an emergency operations dispatcher, not a citizen and not a
developer. They need three things quickly: whether USGS actually recorded an
event, who nearby is least able to absorb it, and which agency gets the first
call. That data is public and federal, but it lives in systems that do not talk
to each other, so somebody currently assembles it by hand under pressure.

Call that person the **dispatcher** everywhere. The code, the README and the
API surface were converged on that term; the slides have not been checked.
Comments in `agents/` and `rag/` still say "citizen" in a few places. One of
those is deliberate: `skill_server.py` says "no citizen-facing audio" to mark
what AEGIS is not, and converging it would invert the sentence.

## The governing principle

**Refuse rather than fabricate.** A brief that says what it could not establish
is a success. A fluent brief with an unsupported claim is a failure, even if it
looks better. Every design decision follows from that.

A concrete consequence: the agency routing table is generated programmatically
from hazardous facility data, never written by the model, because during
development the model silently dropped agencies and a missing row is a missed
call in a crisis.

## Architecture

Six agents run in sequence, each owning exactly one decision:

| Layer | Agent | Decision it owns |
|---|---|---|
| 1 Perception | `agents/intake_agent.py` | Is this a valid incident, or must the dispatcher be prompted? |
| 2 Reasoning | `agents/orchestrator_agent.py` | Which cluster and agency handle this? |
| 3 Knowledge | `agents/rag_knowledge_agent.py` | Does retrieval clear the confidence threshold, or retry? |
| 4 Tools | `agents/data_bridge_agent.py` | Seismic, demographic and hazmat lookups (see provenance below) |
| 5 Governance | `agents/overseer_agent.py` | Is the output supported by its cited source? |
| 6 Action | `agents/synthesis_agent.py` | Which of three output states does validation authorize? |

`pipeline.py` drives the sequence. `governance/output_states.py` defines the
three terminal states: `CONFIRMED_DELIVERY`, `RETRY_CORRECTED_DELIVERY`,
`HONEST_FALLBACK`.

**Data provenance.** Not every source is live, and UI copy has twice drifted
into claiming they all are. Per request the bridge makes four uncached HTTP
calls: USGS, the Census geocoder, FEMA OpenFEMA and IFRC GO. The last two fire
unconditionally through `_build_external_operational_picture()`, which merges
them via `governance/external_harmonization.py` and fails soft to
`status: unavailable`. CDC SVI, HHS emPOWER and EPA TRI are files bundled in
`data/`, read from disk behind `@lru_cache(maxsize=1)`. The unit suite runs
offline; the app does not. Describe the split accurately in anything a
dispatcher reads.

Retrieval happens before generation, and governance happens before delivery.
Neither order is negotiable. Note that the Orchestrator (layer 2) does run
before the RAG agent (layer 3) in `pipeline.py`, so the slogan "retrieval before
reasoning" in the README and in the `pipeline.py` step 4 comment is about the
LLM, not about routing. What the code guarantees is that nothing reaches
`synthesis.generate_candidates()` ungrounded.

## The provider layer

`providers/` holds the LLM abstraction (`anthropic`, `openai_compat`, `watsonx`).
It was developed on `feat/provider-abstraction` and is merged; that branch still
exists locally and on origin but is not where the work lives.
`SynthesisAgent` asks for text and gets text; it does not know or care which
model answered. `get_provider()` resolves from `LLM_PROVIDER` in `.env`, or
auto-detects from whichever credentials are present.

Everything that makes a brief a brief stays in `synthesis_agent.py`: the prompt
contract, the beam schedule, preamble stripping, header normalization.
Vendor-specific auth and endpoint handling belongs in a provider module.

When adding a provider, use `requests` rather than a vendor SDK. The repo
deliberately has no vendor SDK dependencies, which is part of why the unit
suite runs from a bare clone.

## Commands

```bash
source aegis/bin/activate          # venv is named for the project, not .venv

python -m pytest tests/test_units.py -q        # 46 tests, offline, ~0.3s
python -m pytest tests/test_integration.py -q  # makes real API calls

python main.py                     # CLI validation run
uvicorn orchestrate.skill_server:app --reload  # the service Cloud Run runs
```

**Install order matters.** Install CPU-only torch before `requirements.txt`, or
`sentence-transformers` pulls the CUDA-bundled wheel (roughly 3 GB of `nvidia-*`
packages) onto machines with no NVIDIA hardware:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

The `Dockerfile` already does this in the right order. Local setup docs do not.

## Invariants

- **The unit suite must stay green and stay offline.** No network, no API key, no
  data preparation, no virtualenv required. That zero-setup property is
  deliberate and is the repo's strongest asset. Do not add a test to
  `tests/test_units.py` that needs any of those. The rule is the property, not a
  test count: counts quoted elsewhere are informational and will drift, but this
  invariant holds whatever the number is.
- **Never weaken a test to make it pass.** Report the failure instead.
- **Never let a broken dependency masquerade as an honest fallback.** If the
  provider fails to authenticate or the request is rejected, that must surface
  as an error. `HONEST_FALLBACK` means the evidence did not support a claim, not
  that the plumbing is broken. These must be distinguishable to the dispatcher.
- Running the pipeline writes to `chroma_db/`, which is tracked in git. Run
  `git checkout -- chroma_db/` before committing so diffs stay scoped.
- Conventional commits (`fix:`, `docs:`, `feat:`, `chore:`).
- No em dashes in code comments, docs, or commit messages. Use commas, colons,
  parentheses, or separate sentences.

## Deployment

Google Cloud Run runs `orchestrate.skill_server:app` via uvicorn, per the
`Dockerfile` CMD. **`orchestrate/` is live production code, not competition
leftovers.** It also serves the entire front end: `orchestrate/dashboard.html`,
returned by `skill_server.py` at both `/` and `/about`.

Firebase Hosting is only a front door. `public/` holds nothing but `.gitkeep`,
and `firebase.json` rewrites `**` to the Cloud Run service, so a UI change ships
on a Cloud Run deploy alone. Run `firebase deploy` only if the rewrites change.
The public URL is aegis-synthesizer.web.app.

Railway is gone. Any remaining comments or docs referencing it are stale.
`chroma_db/` and `data/` are committed so the Cloud Run image build is
self-contained (baked at build time via `RUN python -m rag.ingest`).

## Key config values

In `config.py`: `BEAM_WIDTH` 4, `MAX_NEW_TOKENS` 2048 (env-configurable), `MAX_RETRIES` 2,
`CONFIDENCE_THRESHOLD` 0.45, `CITATION_ALIGN_THRESHOLD` 0.55,
`SEISMIC_MIN_MAGNITUDE` 1.5 (demo mode; 3.0 is the production value from the
paper), `EMBEDDING_MODEL` all-MiniLM-L6-v2, `SVI_THRESHOLD` 0.75.

## Known issues

- Reasoning models (e.g. `gpt-oss`) spend part of the token budget on hidden
  reasoning before emitting content. `MAX_NEW_TOKENS` must be large enough to
  cover reasoning plus the brief, or the model returns empty content. It is now
  env-configurable (default 2048); tune it per model without a rebuild.
- `test_usgs_response_has_distance_field` asserts `distance_from_incident_km`
  exists in `usgs_live`, but the `DataBridgeAgent` CLEAR branch (no recent
  events in region) omits the key entirely. The test outcome therefore depends
  on real seismic activity at run time.
- `governance/audit_log.py` writes the audit log locally (`export()` dumps JSON
  to disk) and `rag/vector_store.py` uses a local Chroma client with a local
  embedding model (`all-MiniLM-L6-v2`). Neither has a production backend behind
  it. Treat those two as absent.
- Granite Guardian is the exception to the line above: implemented, not absent.
  `OverseerAgent._granite_guardian_check` (`agents/overseer_agent.py:92`) makes a
  real watsonx call, gated on `USE_GRANITE_GUARDIAN`, which defaults to false in
  both `config.py` and `.env.example`. Two further limits when it is enabled: it
  is skipped for `stage == "output"` by design, because it false-positives on
  legitimate hazmat and infrastructure language, and a Guardian failure falls
  back to heuristic moderation with `guardian_error` recorded rather than
  passing silently. Off by default and not in the shipping path, but do not
  describe it as missing.
- The SVI CSV (`data/svi_2022_us_tract.csv`) is committed, all 61 MB of it,
  covering 72,837 US tracts when only Ohio and Oklahoma are used.

## Working style

State assumptions against the actual schema and the actual code rather than
against the README, which overclaims in several places. When something looks
wrong, write it down as a finding rather than fixing it inside an unrelated
change.