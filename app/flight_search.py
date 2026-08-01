"""Real-world flight search index – v0.25.55.

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

    Supports multi-term queries by splitting on whitespace and intersecting
    per-term results.  For example, "EDDF A320" matches flights where any
    indexed field contains "EDDF" AND any indexed field contains "A320".

    If the index is empty or the query is blank, returns all flights.
    If the index fails, falls back to direct field matching.
    """
    terms: list[str] = [t.strip() for t in str(query or "").strip().lower().split() if t.strip()]
    if not terms:
        return list(_flights)
    if not _index:
        return _direct_field_search(terms)
    try:
        # Search each term independently by token-prefix union, then intersect across terms
        all_matched: set[int] | None = None
        for term in terms:
            term_clean = term.replace("-", "").replace(" ", "")
            tokens = _tokenize(term_clean)
            term_matched: set[int] = set()
            for token in tokens:
                idx_set = _index.get(token)
                if idx_set is not None:
                    term_matched |= idx_set
            if not term_matched:
                return []  # No flight matched this term → empty result
            if all_matched is None:
                all_matched = term_matched
            else:
                all_matched &= term_matched
            if not all_matched:
                return []  # Intersection empty — no flight matches all terms
        if all_matched is None:
            return []
        results = [_flights[i] for i in sorted(all_matched)]
        # v0.25.55: exact-match ranking boost
        _boost_exact_matches(results, terms)
        results.sort(key=lambda f: -(f.get("rank_score") or 0))
        return results
    except Exception as exc:
        _log.warning("[SearchIndex] Index search failed, falling back to direct match: %s", exc)
        return _direct_field_search(terms)


def _direct_field_search(terms: list[str]) -> list[dict[str, Any]]:
    """Per-field substring match across key fields when the index is unavailable.

    Each term must match at least one indexed field.  All terms must match for
    a flight to be included (AND logic).
    """
    if not terms:
        return list(_flights)
    SEARCH_FIELDS = ("callsign", "origin_icao", "destination_icao",
                     "origin_name", "destination_name",
                     "airline_name", "airline_icao",
                     "aircraft_type", "aircraft_icao_type",
                     "registration", "mode_s")
    results: list[dict[str, Any]] = []
    for flight in _flights:
        flight_matches = True
        for term in terms:
            term_clean = term.replace("-", "").replace(" ", "")
            term_found = False
            for field in SEARCH_FIELDS:
                val = str(flight.get(field) or "").lower().replace("-", "").replace(" ", "")
                if term_clean in val:
                    term_found = True
                    break
            if not term_found:
                flight_matches = False
                break
        if flight_matches:
            results.append(flight)
    results.sort(key=lambda f: -(f.get("rank_score") or 0))
    return results


def _boost_exact_matches(results: list[dict[str, Any]], terms: list[str]) -> None:
    """v0.25.55: boost rank_score for exact-match results so they sort above
    prefix-only matches.

    For each search term, if a flight has an exact field match (after
    normalization), add +50 to its rank_score.
    """
    for term in terms:
        term_norm = term.lower().replace("-", "").replace(" ", "")
        for f in results:
            matched_exact = False
            for field in ("callsign", "origin_icao", "destination_icao",
                          "aircraft_icao_type", "registration", "mode_s"):
                val = str(f.get(field) or "").lower().replace("-", "").replace(" ", "")
                if val == term_norm:
                    matched_exact = True
                    break
            if matched_exact:
                f["rank_score"] = (f.get("rank_score") or 0) + 50


def index_count() -> int:
    return len(_flights)


def is_index_ready() -> bool:
    return len(_index) > 0
