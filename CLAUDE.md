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
slides currently disagree on this term; dispatcher is the one to converge on.

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
| 4 Tools | `agents/data_bridge_agent.py` | USGS, SVI, emPOWER, EPA TRI lookups |
| 5 Governance | `agents/overseer_agent.py` | Is the output supported by its cited source? |
| 6 Action | `agents/synthesis_agent.py` | Which of three output states does validation authorize? |

`pipeline.py` drives the sequence. `governance/output_states.py` defines the
three terminal states: `CONFIRMED_DELIVERY`, `RETRY_CORRECTED_DELIVERY`,
`HONEST_FALLBACK`.

Retrieval happens before reasoning, and governance happens before delivery.
Neither order is negotiable.

## The provider layer

`providers/` holds the LLM abstraction, added on `feat/provider-abstraction`.
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

python -m pytest tests/test_units.py -q        # 52 tests, offline, ~0.4s
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

- **The 52 unit tests must stay green and must stay offline.** No network, no
  API key, no data preparation, no virtualenv required. That zero-setup property
  is deliberate and is the repo's strongest asset. Do not add a test to
  `tests/test_units.py` that needs any of those.
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
leftovers.** The front end is Firebase Hosting (`firebase.json`, `public/`),
at aegis-synthesizer.web.app.

Railway is gone. Comments and docs still referencing it are stale, including
the `.gitignore` note explaining why `chroma_db/` is committed.

## Key config values

In `config.py`: `BEAM_WIDTH` 4, `MAX_NEW_TOKENS` 700, `MAX_RETRIES` 2,
`CONFIDENCE_THRESHOLD` 0.45, `CITATION_ALIGN_THRESHOLD` 0.55,
`SEISMIC_MIN_MAGNITUDE` 1.5 (demo mode; 3.0 is the production value from the
paper), `EMBEDDING_MODEL` all-MiniLM-L6-v2, `SVI_THRESHOLD` 0.75.

## Known issues

- `providers/*.is_configured()` only checks that a credential is non-empty, so
  placeholder values from `.env.example` count as configured. After
  `cp .env.example .env`, auto-detect selects a provider that cannot
  authenticate, every beam returns empty, and the pipeline degrades to a
  fallback instead of failing loudly.
- `providers/openai_compat.py` discards the response body on failure, so a
  non-2xx or unexpected shape surfaces only as a `KeyError` name. Log the status
  code and body.
- `_normalize_section_headers` in `synthesis_agent.py` only matches headers that
  already carry an asterisk, so a model emitting a bare `[HAZARD STATUS]` is
  left unnormalized. Validation still passes because the Overseer checks the
  plain bracket strings. Cosmetic, but it matters more now that header style
  varies by provider.
- `test_usgs_response_has_distance_field` asserts `distance_from_incident_km`
  exists in `usgs_live`, but the `DataBridgeAgent` CLEAR branch (no recent
  events in region) omits the key entirely. The test outcome therefore depends
  on real seismic activity at run time.
- `app.py` imports streamlit, which is not in `requirements.txt`.
- The README's IBM Tools table claims four watsonx components. Two are not
  implemented: `governance/audit_log.py` writes locally and `rag/vector_store.py`
  uses a local embedding model, both with comments describing what production
  would do. The README also says the SVI CSV is not in git, but it is committed,
  all 61 MB of it, covering 72,837 US tracts when only Ohio and Oklahoma are used.

## Working style

State assumptions against the actual schema and the actual code rather than
against the README, which overclaims in several places. When something looks
wrong, write it down as a finding rather than fixing it inside an unrelated
change.