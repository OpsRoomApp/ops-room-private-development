"""Real-world flight search index – v0.25.49.

Builds an in-memory searchable index from normalized flight records and
provides a case-insensitive, partial-match search with direct-field fallback.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("opsroom.realworld.search")

_SEARCH_FIELDS: tuple[str, ...] = (
    "callsign", "callsign_icao", "callsign_iata",
    "airline_name", "airline_icao", "airline_iata",
    "origin_icao", "origin_iata", "origin_name", "origin_city",
    "destination_icao", "destination_iata", "destination_name", "destination_city",
    "aircraft_type", "aircraft_icao_type", "aircraft_manufacturer",
    "registration", "mode_s",
)

# Map of {token_lower: set(flight_index)}
_index: dict[str, set[int]] = {}
_flights: list[dict[str, Any]] = []


def _tokenize(text: str) -> set[str]:
    """Produce normalized search tokens from a string."""
    t = str(text or "").strip().lower().replace("-", "").replace(" ", "")
    tokens: set[str] = set()
    if t:
        tokens.add(t)
        # Add progressive prefixes for partial matching (min 2 chars)
        for i in range(2, len(t) + 1):
            tokens.add(t[:i])
    return tokens


def build_search_index(records: list[dict[str, Any]]) -> None:
    """(Re)build the search index from a list of normalized flight records."""
    global _index, _flights
    _flights = list(records)
    _index = {}
    for idx, flight in enumerate(records):
        for field in _SEARCH_FIELDS:
            val = flight.get(field)
            if val:
                for token in _tokenize(str(val)):
                    _index.setdefault(token, set()).add(idx)


def search_index(query: str) -> list[dict[str, Any]]:
    """Return flights matching the search query via the index.

    If the index is empty or the query is blank, returns all flights.
    If the index fails, falls back to direct field matching.
    """
    q = str(query or "").strip().lower().replace("-", "").replace(" ", "")
    if not q:
        return list(_flights)
    if not _index:
        return _direct_field_search(q)
    try:
        tokens = _tokenize(q)
        if not tokens:
            return list(_flights)
        # Intersection of all token-matched index sets
        matched: set[int] | None = None
        for token in tokens:
            idx_set = _index.get(token)
            if idx_set is None:
                return []
            if matched is None:
                matched = set(idx_set)
            else:
                matched &= idx_set
        if matched is None:
            return []
        results = [_flights[i] for i in sorted(matched)]
        # Sort by rank_score descending
        results.sort(key=lambda f: -(f.get("rank_score") or 0))
        return results
    except Exception as exc:
        _log.warning("[SearchIndex] Index search failed, falling back to direct match: %s", exc)
        return _direct_field_search(q)


def _direct_field_search(query: str) -> list[dict[str, Any]]:
    """Direct substring match across key fields when the index is unavailable."""
    q = str(query or "").strip().lower()
    if not q:
        return list(_flights)
    results: list[dict[str, Any]] = []
    for flight in _flights:
        for field in ("callsign", "origin_icao", "destination_icao",
                       "airline_name", "aircraft_type", "registration"):
            val = str(flight.get(field) or "").lower().replace("-", "").replace(" ", "")
            if q in val:
                results.append(flight)
                break
    results.sort(key=lambda f: -(f.get("rank_score") or 0))
    return results


def index_count() -> int:
    return len(_flights)


def is_index_ready() -> bool:
    return len(_index) > 0
