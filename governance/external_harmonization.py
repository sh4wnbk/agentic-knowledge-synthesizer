"""
governance/external_harmonization.py

Shared normalization and merge logic for external disaster feeds.
This keeps source-specific parsing out of agent prompt logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _freshness_score(updated_at: str | None) -> float:
    dt = _parse_dt(updated_at)
    if not dt:
        return 0.35
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    if age_hours <= 24:
        return 0.95
    if age_hours <= 72:
        return 0.8
    if age_hours <= 168:
        return 0.65
    return 0.45


def normalize_fema_declarations(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = raw.get("DisasterDeclarationsSummaries", []) if isinstance(raw, dict) else []
    out: list[dict[str, Any]] = []
    fetched_at = _now_iso()
    for row in rows:
        disaster_number = row.get("disasterNumber")
        event_id = str(disaster_number or "")
        out.append(
            {
                "source": "FEMA",
                "event_id": event_id,
                "event_type": row.get("incidentType") or "unknown",
                "status": row.get("declarationType") or "declared",
                "severity": None,
                "geo": {
                    "country": "US",
                    "state": row.get("state"),
                    "admin1": row.get("state"),
                    "admin2": row.get("designatedArea"),
                    "lat": None,
                    "lon": None,
                },
                "updated_at": row.get("lastRefresh"),
                "fetched_at": fetched_at,
                "freshness_score": _freshness_score(row.get("lastRefresh")),
                "confidence": 0.82,
                "provenance_url": (
                    "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
                    f"?$filter=disasterNumber%20eq%20{disaster_number}"
                    if disaster_number is not None
                    else "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
                ),
            }
        )
    return out


def normalize_ifrc_events(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = raw.get("results", []) if isinstance(raw, dict) else []
    out: list[dict[str, Any]] = []
    fetched_at = _now_iso()
    for row in rows:
        dtype = row.get("dtype") or {}
        countries = row.get("countries") or []
        first_country = countries[0] if countries else {}
        out.append(
            {
                "source": "IFRC",
                "event_id": str(row.get("id") or ""),
                "event_type": dtype.get("name") or "unknown",
                "status": row.get("status") or row.get("appeal_status") or "active",
                "severity": None,
                "geo": {
                    "country": first_country.get("iso3") or first_country.get("name"),
                    "state": None,
                    "admin1": None,
                    "admin2": None,
                    "lat": None,
                    "lon": None,
                },
                "updated_at": row.get("modified_at") or row.get("updated_at"),
                "fetched_at": fetched_at,
                "freshness_score": _freshness_score(row.get("modified_at") or row.get("updated_at")),
                "confidence": 0.76,
                "provenance_url": (
                    f"https://go.ifrc.org/emergencies/{row.get('id')}"
                    if row.get("id") is not None
                    else "https://goadmin.ifrc.org/api/v2/event/"
                ),
            }
        )
    return out


def _location_fit(event: dict[str, Any], state_abbr: str | None, country_hint: str | None) -> float:
    geo = event.get("geo", {})
    if event.get("source") == "FEMA":
        if state_abbr and geo.get("state") and str(geo.get("state")).upper() == str(state_abbr).upper():
            return 0.95
        return 0.55
    if event.get("source") == "IFRC":
        if not country_hint:
            return 0.55
        country = (geo.get("country") or "").upper()
        if country in (country_hint.upper(), "USA", "US", "UNITED STATES"):
            return 0.7
        return 0.45
    return 0.5


def _event_type_fit(event: dict[str, Any], crisis_type: str | None) -> float:
    if not crisis_type:
        return 0.6

    event_type = str(event.get("event_type") or "").lower()
    if crisis_type in ("induced_seismicity", "natural_seismicity"):
        keys = ["earthquake", "seismic", "geophysical", "volcan"]
    elif crisis_type == "flooding":
        keys = ["flood", "storm", "cyclone", "hurricane", "typhoon"]
    elif crisis_type == "fire":
        keys = ["fire", "wildfire"]
    else:
        return 0.6

    return 0.95 if any(k in event_type for k in keys) else 0.45


def _is_stale(event: dict[str, Any], min_freshness: float) -> bool:
    freshness = float(event.get("freshness_score", 0.0))
    return freshness < min_freshness


def filter_events_by_relevance(
    events: list[dict[str, Any]],
    state_abbr: str | None,
    crisis_type: str | None,
    country_hint: str | None = "US",
) -> list[dict[str, Any]]:
    """
    Pre-filter events before scoring so top candidates are locally actionable.
    Returns only strict matches. If none match, callers should surface
    an explicit unavailable/no-relevant-events state.
    """
    if not events:
        return []

    strict: list[dict[str, Any]] = []
    for event in events:
        geo = event.get("geo", {})
        source = event.get("source")
        location_ok = False

        if source == "FEMA":
            if state_abbr and str(geo.get("state") or "").upper() == str(state_abbr).upper():
                location_ok = True
        elif source == "IFRC":
            country = str(geo.get("country") or "").upper()
            if country_hint and country in (country_hint.upper(), "USA", "US", "UNITED STATES"):
                location_ok = True
        else:
            location_ok = True

        if location_ok and _event_type_fit(event, crisis_type) >= 0.6:
            strict.append(event)

    return strict


def merge_external_sources(
    fema_events: list[dict[str, Any]],
    ifrc_events: list[dict[str, Any]],
    state_abbr: str | None,
    crisis_type: str | None,
    country_hint: str | None = "US",
    min_freshness: float = 0.5,
) -> dict[str, Any]:
    merged = list(fema_events) + list(ifrc_events)
    merged = filter_events_by_relevance(
        events=merged,
        state_abbr=state_abbr,
        crisis_type=crisis_type,
        country_hint=country_hint,
    )

    non_stale = [e for e in merged if not _is_stale(e, min_freshness)]
    candidate_events = non_stale if non_stale else merged

    ranked = []
    for event in candidate_events:
        freshness = float(event.get("freshness_score", 0.5))
        confidence = float(event.get("confidence", 0.5))
        location_fit = _location_fit(event, state_abbr, country_hint)
        event_fit = _event_type_fit(event, crisis_type)
        priority = round(
            (0.40 * location_fit)
            + (0.25 * freshness)
            + (0.20 * confidence)
            + (0.15 * event_fit),
            3,
        )
        cloned = dict(event)
        cloned["event_fit"] = event_fit
        cloned["priority_score"] = priority
        ranked.append(cloned)

    # Geo-first partition: prioritize direct domestic relevance.
    primary = []
    secondary = []
    for event in ranked:
        geo = event.get("geo", {})
        if event.get("source") == "FEMA":
            if state_abbr and str(geo.get("state") or "").upper() == str(state_abbr).upper():
                primary.append(event)
            else:
                secondary.append(event)
        elif event.get("source") == "IFRC":
            country = str(geo.get("country") or "").upper()
            if country in ("USA", "US", "UNITED STATES"):
                primary.append(event)
            else:
                secondary.append(event)
        else:
            secondary.append(event)

    primary.sort(key=lambda e: e.get("priority_score", 0.0), reverse=True)
    secondary.sort(key=lambda e: e.get("priority_score", 0.0), reverse=True)
    top = (primary + secondary)[:5]
    return {
        "status": "available" if ranked else "unavailable",
        "sources": {
            "fema_count": len(fema_events),
            "ifrc_count": len(ifrc_events),
            "candidate_count": len(candidate_events),
        },
        "source_validation_urls": {
            "fema_portal": "https://www.fema.gov/disaster/declarations",
            "fema_api": "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
            "ifrc_portal": "https://go.ifrc.org/emergencies",
            "ifrc_api": "https://goadmin.ifrc.org/api/v2/event/",
        },
        "top_events": top,
        "merge_policy": (
            "priority=0.40*location_fit+0.25*freshness+0.20*confidence+0.15*event_fit; "
            "primary_partition=FEMA_state_match_or_IFRC_US; stale_cutoff=freshness>=0.50"
        ),
    }
