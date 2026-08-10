"""Build-time taxiway bundle extractor for OPS ROOM.

Reads the local Little Navmap MSFS scenery database (read-only) and packs the
taxiway + parking-taxiway segments (types ``T`` / ``PT``) into a compact,
per-airport, zlib-compressed bundle stored in ``opsroom_aviation.sqlite`` so
users WITHOUT Little Navmap installed still get real taxiway geometry for the
map surface layers and the NOTAM closure-marker hold-short derivation.

Why a bundle instead of a flat table: the full-world flat ``surface_taxi_path``
table is ~143 MB in SQLite, while the zlib bundle of the same segments is
~16 MB -- small enough to ship inside the existing aviation database.

Usage:
    python tools/build_taxi_bundle.py [--source <LNM msfs sqlite>] [--out <aviation sqlite>]

The LNM database is auto-detected from the standard Little Navmap location when
``--source`` is omitted. The aviation DB defaults to
``app/data/navigation/opsroom_aviation.sqlite``.

The table created is ``surface_taxi_bundle(airport_id INTEGER PRIMARY KEY,
airport_ident TEXT, segment_count INTEGER, payload BLOB)``. ``payload`` is the
zlib stream of a packed binary array; see ``decode_taxi_bundle()`` in
``app/aviation_data.py`` for the exact layout. The operation is idempotent:
running it again replaces the existing bundle rows.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import struct
import sys
import time
import zlib
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = APP_ROOT / "app" / "data" / "navigation" / "opsroom_aviation.sqlite"


def _auto_detect_source() -> Path:
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "ABarthel" / "little_navmap_db" / "little_navmap_msfs.sqlite",
        Path.home() / "AppData" / "Roaming" / "ABarthel" / "little_navmap_db" / "little_navmap_msfs.sqlite",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "Little Navmap MSFS database not found. Pass --source <path/to/little_navmap_msfs.sqlite>"
    )


def _pack_airport(rows: list[tuple]) -> bytes:
    """Pack segment rows into a compact binary payload (zlib applied by caller)."""
    out = bytearray()
    out += struct.pack("<I", len(rows))
    for taxi_path_id, airport_id, seg_type, surface, width_ft, name, slon, slat, elon, elat in rows:
        name_b = (str(name or "")[:40]).encode("utf-8")
        type_b = (str(seg_type or "")[:2]).encode("utf-8")
        surf_b = (str(surface or "")[:20]).encode("utf-8")
        out += struct.pack("<I", len(name_b)) + name_b
        out += struct.pack("<B", len(type_b)) + type_b
        out += struct.pack("<B", len(surf_b)) + surf_b
        out += struct.pack("<f f f f f", float(width_ft or 0.0), float(slon), float(slat), float(elon), float(elat))
    return zlib.compress(bytes(out), level=9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None, help="Little Navmap MSFS sqlite (auto-detected if omitted)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Target opsroom_aviation.sqlite")
    parser.add_argument("--min-airports", type=int, default=0, help="Debug: only airports with at least N segments")
    args = parser.parse_args()

    source = Path(args.source) if args.source else _auto_detect_source()
    out = Path(args.out)
    if not source.is_file():
        raise SystemExit(f"Source database not found: {source}")
    if not out.is_file():
        raise SystemExit(f"Target aviation database not found: {out}")

    t0 = time.time()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(str(out))
    try:
        # Group segments by airport in SQL (LIMIT-style guard not needed; LNM
        # has no giant single-airport payloads above ~10k segments).
        groups: dict[int, list[tuple]] = {}
        idents: dict[int, str] = {}
        for r in src.execute(
            """
            SELECT t.taxi_path_id, t.airport_id, t.type, t.surface, t.width, t.name,
                   t.start_lonx, t.start_laty, t.end_lonx, t.end_laty
            FROM taxi_path t
            WHERE t.type IN ('T','PT')
              AND t.start_lonx IS NOT NULL AND t.start_laty IS NOT NULL
              AND t.end_lonx IS NOT NULL AND t.end_laty IS NOT NULL
            ORDER BY t.airport_id, t.taxi_path_id
            """
        ):
            aid = int(r[1])
            if args.min_airports and len(groups.get(aid, [])) >= args.min_airports:
                continue
            groups.setdefault(aid, []).append(tuple(r))
        ids = {aid for aid in groups}
        for r in src.execute(
            f"SELECT airport_id, ident FROM airport WHERE airport_id IN ({','.join(str(a) for a in ids)})"
        ):
            idents[int(r[0])] = str(r[1])
        src.close()

        dst.execute(
            """
            CREATE TABLE IF NOT EXISTS surface_taxi_bundle (
                airport_id INTEGER PRIMARY KEY,
                airport_ident TEXT,
                segment_count INTEGER,
                payload BLOB
            )
            """
        )
        dst.execute("DELETE FROM surface_taxi_bundle")
        dst.commit()

        total_segments = 0
        bundled = 0
        for aid, rows in groups.items():
            if not rows:
                continue
            packed = _pack_airport(rows)
            dst.execute(
                "INSERT OR REPLACE INTO surface_taxi_bundle (airport_id, airport_ident, segment_count, payload) VALUES (?,?,?,?)",
                (aid, idents.get(aid, ""), len(rows), packed),
            )
            total_segments += len(rows)
            bundled += 1
        dst.commit()

        size_bytes = sum(
            r[0] for r in dst.execute("SELECT LENGTH(payload) FROM surface_taxi_bundle")
        )
        print(
            f"OK  airports={bundled}  segments={total_segments}  "
            f"bundle={size_bytes/1024/1024:.1f} MB (zlib)  elapsed={time.time()-t0:.1f}s"
        )
        print(f"    target: {out}")
        return 0
    finally:
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
