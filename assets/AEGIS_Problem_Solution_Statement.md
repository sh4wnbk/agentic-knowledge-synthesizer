# AEGIS — Written Problem & Solution Statement

**IBM SkillsBuild AI Experiential Learning Lab 2026 | Government & Public Services**
**Author: Shawn Blackman | Lehman College CUNY | B.S. Environmental Science**
**Prototype: github.com/sh4wnbk/agentic-knowledge-synthesizer**

---

## The Problem

When a disposal-well-induced earthquake strikes Ohio or Oklahoma, the Emergency Operations Center supervisor — the trained professional managing the response — needs three answers immediately: Was there a confirmed earthquake? Which residents are most at risk? Which agency does she call first?

The data already exists. The U.S. Geological Survey tracks seismic events in near real time. The CDC publishes a Social Vulnerability Index (SVI) score for every census tract in the country. The Department of Health and Human Services tracks how many residents in each county depend on electricity for ventilators, oxygen machines, and other powered medical equipment. The EPA maintains a registry of active hazardous industrial facilities. These datasets are public, federal, and accurate.

But they do not talk to each other.

In practice, answering those three questions means manually opening multiple databases, cross-referencing a census tract number against a vulnerability score, looking up county codes to find residents at medical risk, and consulting a separate registry for nearby hazmat facilities — all under pressure, while the phone keeps ringing.

The problem is not missing data. It is that a trained human professional is filling the coordination gap by hand, at the moment when that person's attention is most needed elsewhere.

## The Solution

AEGIS — Agentic Emergency Geospatial Intelligence Synthesizer — is a six-agent AI pipeline that closes that coordination gap automatically.

A dispatcher submits one incident report in plain language. AEGIS pulls a live earthquake reading from the USGS, resolves the affected census tract, retrieves the community's SVI score from the CDC, counts electricity-dependent residents from the HHS emPOWER program, and scans for EPA-registered hazardous facilities within 25 kilometers of the incident. It fuses all of this together, runs quality checks, and returns a validated, three-section agency routing brief in under 30 seconds.

The output always contains exactly three sections: confirmed seismic data with geographic verification, the community's vulnerability profile, and a tiered agency routing table showing who to contact immediately and in what order. If hazardous facilities are detected near the incident, the state environmental agency automatically moves to Tier 1. That decision is triggered by the data, not by the AI.

Before any output reaches the dispatcher, three quality checks run automatically. If the system cannot produce a validated brief, it says so — explicitly — rather than delivering a confident-sounding wrong answer. A system that knows how to say "I don't know" is safer in an emergency context than one that always sounds certain.

AEGIS does not make decisions. It informs the trained professional who does.

## Proof of Concept

Validated across four test cases in two states — Youngstown and Niles, Ohio; Cushing and Pawnee, Oklahoma — all returning confirmed briefs with output quality scores between 63% and 77%. The Youngstown case returned an SVI score of 0.9575 (top vulnerability quartile), flagged 59 hazardous industrial facilities triggering automatic EPA tier promotion, and identified 2,909 electricity-dependent residents requiring priority evacuation consideration — in a single structured response.

The right information. The right person. Under 30 seconds.
